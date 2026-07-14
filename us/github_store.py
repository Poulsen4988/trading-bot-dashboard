"""
Lille GitHub content-store helper til Claude routines og GitHub Actions.

Bruger GITHUB_TOKEN eller DASHBOARD_PAT fra environment. Ingen tokens må
hardcodes i kode eller prompts.

VIGTIGT — tre driftstilstande:

1) GITHUB ACTIONS (GITHUB_ACTIONS=true): præcis klassisk adfærd — læs/skriv
   direkte via api.github.com Contents API med retry + 409/422-håndtering.
   INGEN lokal fallback og ingen circuit breaker: en fejlet skrivning
   returnerer False og skal behandles som fejl af kalderen (workflowets
   git-step committer i øvrigt lokale filer for fetch_data.yml).

2) RUTINE-SANDKASSE / OFFLINE (GITHUB_STORE_OFFLINE=1 eller blokeret API):
   Sandkassen blokerer ofte api.github.com (HTTP 403 "GitHub access is not
   enabled for this session"). Derfor:
   - Læsninger falder tilbage til det lokale repo-klon (rutinens sandkasse
     kloner main frisk ved sessionstart, så lokale filer er aktuelle).
   - Skrivninger gemmes lokalt i klonen OG registreres i pending-manifestet
     ".github_store_pending.json" i repo-roden. Rutinen SKAL til sidst pushe
     de pending filer til main via GitHub MCP-værktøjet
     mcp__github__push_files (owner=Poulsen4988, repo=trading-bot-dashboard,
     branch=main) — og derefter køre `python github_store.py --clear`.
   - `python github_store.py` printer pending-listen (JSON på stdout).
   - En circuit breaker slår automatisk i offline-tilstand efter 401 /
     policy-403 fra API'et eller gentagne netværksfejl, så en blokeret
     session ikke spilder minutter på dømte retries. Rate-limit-403 fra
     GitHub selv tæller kun som transient fejl.

3) LOKAL KØRSEL med token: som (2) — API først, lokal fallback ved fejl.

raise_on_error-kontrakten (kritiske reads som data.json i paper_trader):
- API-fejl af transient art (5xx/netværk) → der HÆVES GitHubReadError som
  før — vi handler aldrig mod potentielt forældet lokal state pga. et blip.
- Politik-blokering (401/policy-403) eller tvungen offline → lokal klon
  bruges (i sandkassen ER klonen frisk). Findes filen heller ikke lokalt,
  hæves GitHubReadError — aldrig stille default/tom state.

Læsninger i samme session ser altid egne skrivninger: get_json tjekker
pending-manifestet FØR API'et, og put_json skriver filen lokalt
(write-through) når API-skrivningen lykkes. Pending-poster ældre end 24
timer ignoreres og fjernes (beskytter genbrugte arbejdsmapper mod at pushe
forældede filer).

HOLD I SYNK: us/github_store.py er en identisk kopi af denne fil.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except Exception:
    pass

REPO = os.environ.get("DASHBOARD_REPO", "Poulsen4988/trading-bot-dashboard")
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("DASHBOARD_PAT") or ""
API_BASE = f"https://api.github.com/repos/{REPO}/contents"

_MAX_RETRIES = 3
_BACKOFF_SEC = 1.5

# Circuit breaker: efter så mange fejlende API-kald i træk skiftes der til
# offline-tilstand for resten af processen.
_BREAKER_THRESHOLD = 2

# Pending-poster ældre end dette er fra en død session og må ikke genbruges.
_PENDING_MAX_AGE_SEC = 24 * 3600

# I GitHub Actions: klassisk API-only adfærd — ingen fallback, ingen breaker.
_IN_ACTIONS = os.environ.get("GITHUB_ACTIONS", "").lower() == "true"

_FORCED_OFFLINE = os.environ.get("GITHUB_STORE_OFFLINE", "") not in ("", "0")

# _api_down_reason: None (API i brug) | 'forced' | 'policy' | 'transient'
_api_down_reason: str | None = "forced" if _FORCED_OFFLINE else None
_api_fail_streak = 0
_offline_announced = False


def _log(msg: str) -> None:
    """Diagnostik til stderr — stdout er reserveret til script-output
    (fx `python kb_review.py > kb_candidates.json`)."""
    print(msg, file=sys.stderr)


def _repo_root() -> str:
    """Repo-roden = nærmeste mappe opad med .git. API-stier er repo-relative,
    så alle lokale læs/skriv skal også være det (github_store.py kan ligge i
    roden ELLER i us/)."""
    d = os.path.dirname(os.path.abspath(__file__))
    probe = d
    while True:
        if os.path.isdir(os.path.join(probe, ".git")):
            return probe
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    # Intet .git fundet (fx udpakket zip): us/-kopien peger på parent.
    return os.path.dirname(d) if os.path.basename(d) == "us" else d


REPO_ROOT = _repo_root()
PENDING_MANIFEST = os.path.join(REPO_ROOT, ".github_store_pending.json")


class GitHubReadError(RuntimeError):
    """Hævet når en read fejler og kalderen bad om raise_on_error."""


def _fallback_enabled() -> bool:
    """Lokal fallback + pending-staging er slået fra i GitHub Actions
    (dér skal en API-fejl være en rigtig fejl), medmindre offline er tvunget."""
    return _FORCED_OFFLINE or not _IN_ACTIONS


def _api_available() -> bool:
    return bool(TOKEN) and _api_down_reason is None


def _announce_offline(reason: str) -> None:
    global _offline_announced
    if _offline_announced:
        return
    _offline_announced = True
    _log(
        f"[github_store] OFFLINE-TILSTAND: {reason}\n"
        f"[github_store] Læsninger bruger det lokale repo-klon; skrivninger gemmes\n"
        f"[github_store] lokalt og registreres i {os.path.basename(PENDING_MANIFEST)}.\n"
        f"[github_store] HUSK til sidst: push pending filer til branch main via\n"
        f"[github_store] MCP-værktøjet mcp__github__push_files "
        f"(kør `python github_store.py` for listen, `--clear` efter push)."
    )


def _trip_breaker(kind: str, reason: str) -> None:
    global _api_down_reason
    if _api_down_reason is None:
        _api_down_reason = kind
        if _fallback_enabled():
            _announce_offline(reason)
        else:
            _log(f"[github_store] API opgivet for processen: {reason}")


def _is_rate_limit(e: urllib.error.HTTPError) -> bool:
    """GitHubs egne rate-limit svar er 403 men er transiente — de må ikke
    behandles som permanent politik-blokering."""
    try:
        h = e.headers or {}
        if h.get("Retry-After"):
            return True
        if h.get("X-RateLimit-Remaining") == "0":
            return True
        body = e.read() or b""
        return b"rate limit" in body.lower()
    except Exception:
        return False


def _note_api_failure(err: Exception) -> None:
    """Registrér et fejlet API-kald; slå evt. breakeren til (ikke i Actions)."""
    global _api_fail_streak
    if _IN_ACTIONS and not _FORCED_OFFLINE:
        return
    if isinstance(err, urllib.error.HTTPError) and err.code in (401, 403):
        if err.code == 403 and _is_rate_limit(err):
            _api_fail_streak += 1
        else:
            # Auth/policy-fejl (proxyens "GitHub access is not enabled for
            # this session" eller revoked token) heler ikke af sig selv.
            _trip_breaker("policy", f"api.github.com afviste kaldet (HTTP {err.code}).")
            return
    else:
        _api_fail_streak += 1
    if _api_fail_streak >= _BREAKER_THRESHOLD:
        _trip_breaker("transient", f"{_api_fail_streak} API-kald fejlede i træk ({err}).")


def _note_api_success() -> None:
    global _api_fail_streak
    _api_fail_streak = 0


def _headers() -> dict[str, str]:
    headers = {"User-Agent": "TradingBot/1.0"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    return headers


def _urlopen_retry(req: urllib.request.Request, *, retry_status=(500, 502, 503, 504)):
    """urlopen med retry på transiente fejl. Hæver sidste fejl hvis alle forsøg fejler."""
    last_err = None
    for attempt in range(_MAX_RETRIES):
        try:
            return urllib.request.urlopen(req)
        except urllib.error.HTTPError as e:
            last_err = e
            # 404/409/422 mv. håndteres af kalderen — retry ikke her.
            if e.code not in retry_status:
                raise
        except urllib.error.URLError as e:
            last_err = e
        if attempt < _MAX_RETRIES - 1:
            time.sleep(_BACKOFF_SEC * (attempt + 1))
    raise last_err


def _local_path(path: str) -> str:
    return os.path.join(REPO_ROOT, path.replace("/", os.sep))


def _read_local(path: str):
    """Læs repo-relativ fil fra det lokale klon. Returnerer (found, data)."""
    try:
        with open(_local_path(path), encoding="utf-8") as f:
            return True, json.load(f)
    except FileNotFoundError:
        return False, None
    except Exception as e:
        _log(f"[github_store] Kunne ikke læse lokal {path}: {e}")
        return False, None


def _write_local(path: str, data: Any) -> bool:
    try:
        full = _local_path(path)
        os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
        tmp = full + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, full)
        return True
    except Exception as e:
        _log(f"[github_store] FEJL: kunne ikke skrive lokal {path}: {e}")
        return False


def _load_manifest() -> dict:
    """Læs manifestet og fjern forældede poster (>24t — død session)."""
    try:
        with open(PENDING_MANIFEST, encoding="utf-8") as f:
            m = json.load(f)
        if not (isinstance(m, dict) and isinstance(m.get("pending"), dict)):
            return {"version": 1, "pending": {}}
    except FileNotFoundError:
        return {"version": 1, "pending": {}}
    except Exception as e:
        _log(f"[github_store] Kunne ikke læse pending-manifest: {e}")
        return {"version": 1, "pending": {}}

    now = datetime.now(timezone.utc)
    stale = []
    for p, info in m["pending"].items():
        try:
            ts = datetime.strptime(info.get("updated_at", ""), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if (now - ts).total_seconds() > _PENDING_MAX_AGE_SEC:
                stale.append(p)
        except Exception:
            stale.append(p)
    if stale:
        _log(f"[github_store] Ignorerer {len(stale)} forældede pending-poster (>24t): {stale}")
        for p in stale:
            del m["pending"][p]
        _save_manifest(m)
    return m


def _save_manifest(m: dict) -> None:
    try:
        tmp = PENDING_MANIFEST + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=2)
        os.replace(tmp, PENDING_MANIFEST)
    except Exception as e:
        _log(f"[github_store] FEJL: kunne ikke opdatere pending-manifest: {e}")


def _mark_pending(path: str, message: str) -> None:
    m = _load_manifest()
    m["pending"][path] = {
        "message": message,
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    _save_manifest(m)


def _clear_pending(path: str) -> None:
    m = _load_manifest()
    if path in m["pending"]:
        del m["pending"][path]
        _save_manifest(m)


def clear_all_pending() -> int:
    """Tøm manifestet (efter et vellykket MCP-push). Returnerer antal fjernet."""
    m = _load_manifest()
    n = len(m["pending"])
    m["pending"] = {}
    _save_manifest(m)
    return n


def pending_writes() -> list[dict]:
    """Liste over filer skrevet lokalt som stadig mangler at blive pushet til main."""
    m = _load_manifest()
    return [
        {"path": p, "message": info.get("message", "")}
        for p, info in sorted(m["pending"].items())
    ]


def is_pending(path: str) -> bool:
    return path in _load_manifest()["pending"]


def get_json(path: str, default: Any = None, raise_on_error: bool = False) -> tuple[Any, str | None]:
    """Hent JSON. Returnerer (data, sha). sha er None ved lokal læsning.

    Rækkefølge:
    1. Pending-manifest: filer skrevet lokalt i denne session er nyest — brug dem.
    2. GitHub API (hvis token og ikke offline). 404 = filen findes ikke → default.
    3. Lokalt repo-klon som fallback — men KUN når det er sikkert (se
       modulets docstring om raise_on_error-kontrakten).
    """
    # 1) Egen usendt skrivning fra denne session vinder altid.
    if _fallback_enabled() and is_pending(path):
        found, data = _read_local(path)
        if found:
            return data, None

    api_error: Exception | None = None
    if _api_available():
        url = f"{API_BASE}/{path}"
        req = urllib.request.Request(url, headers=_headers())
        try:
            with _urlopen_retry(req) as r:
                payload = json.loads(r.read())
            _note_api_success()
            content = base64.b64decode(payload["content"]).decode("utf-8")
            return json.loads(content), payload.get("sha")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                # Filen findes ikke på main endnu — gyldig tilstand.
                _note_api_success()
                return default, None
            api_error = e
            _note_api_failure(e)
            _log(f"[github_store] API-fejl ved læsning af {path}: HTTP {e.code} {e.reason}")
        except Exception as e:
            api_error = e
            _note_api_failure(e)
            _log(f"[github_store] Netværksfejl ved læsning af {path}: {e}")

    # 3) Lokal fallback. Ved raise_on_error er lokal state kun tilladt når
    # API'et er politik-blokeret/tvunget offline (sandkassen — klonen er
    # frisk) eller der intet token er. Ved transiente API-fejl hæves der som
    # før, så vi aldrig handler mod potentielt forældet state pga. et blip.
    # (_note_api_failure har allerede sat _api_down_reason='policy' hvis
    # dette kald blev politik-blokeret.)
    if _fallback_enabled():
        safe_for_critical = (not TOKEN) or _api_down_reason in ("forced", "policy")
        if not raise_on_error or safe_for_critical:
            found, data = _read_local(path)
            if found:
                if api_error is not None:
                    _log(f"[github_store] Bruger lokal kopi af {path}")
                return data, None
        if raise_on_error:
            if api_error is not None:
                raise GitHubReadError(f"{path}: {api_error}") from api_error
            raise GitHubReadError(
                f"{path}: hverken API ({_api_down_reason or 'intet token'}) eller lokal kopi tilgængelig"
            )
        return default, None

    # GitHub Actions: klassisk adfærd — ingen lokal fallback med token.
    if raise_on_error and api_error is not None:
        raise GitHubReadError(f"{path}: {api_error}") from api_error
    if api_error is not None:
        return default, None
    if not TOKEN:
        found, data = _read_local(path)
        if found:
            return data, None
    return default, None


def _fetch_sha(url: str) -> str | None:
    """Hent eksisterende fil-sha (med retry). 404 → None. Hæver ellers."""
    req = urllib.request.Request(url, headers=_headers())
    try:
        with _urlopen_retry(req) as r:
            return json.loads(r.read()).get("sha")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def put_json(path: str, data: Any, message: str) -> bool:
    """Skriv JSON. Returnerer True hvis filen ER på GitHub, False hvis ikke.
    Udenfor GitHub Actions gemmes filen ved API-fejl lokalt og registreres i
    pending-manifestet (skal derefter pushes via MCP)."""
    if _api_available():
        content = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        b64 = base64.b64encode(content).decode("ascii")
        url = f"{API_BASE}/{path}"
        headers = {**_headers(), "Content-Type": "application/json"}

        # Op til _MAX_RETRIES forsøg; ved 409/422 (sha flyttede sig/manglede
        # pga. samtidig skriver) hentes frisk sha og forsøget gentages.
        for attempt in range(_MAX_RETRIES):
            try:
                sha = _fetch_sha(url)
            except Exception as e:
                _note_api_failure(e)
                if not _api_available():
                    break
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(_BACKOFF_SEC * (attempt + 1))
                    continue
                _log(f"[github_store] API-skrivning af {path} opgivet: kunne ikke hente sha ({e})")
                break

            body = {"message": message, "content": b64}
            if sha:
                body["sha"] = sha
            req = urllib.request.Request(
                url, data=json.dumps(body).encode("utf-8"), method="PUT", headers=headers
            )
            try:
                with urllib.request.urlopen(req) as r:
                    _log(f"[github_store] Gemte {path} (HTTP {r.status})")
                _note_api_success()
                if _fallback_enabled():
                    # Write-through: hold klonen i synk, så senere læsninger i
                    # samme session ser den nye fil selv hvis API'et falder ud.
                    _write_local(path, data)
                    _clear_pending(path)
                return True
            except urllib.error.HTTPError as e:
                if e.code in (409, 422, 500, 502, 503, 504) and attempt < _MAX_RETRIES - 1:
                    grund = "sha-konflikt" if e.code in (409, 422) else f"HTTP {e.code} transient"
                    _log(f"[github_store] {grund} på {path}, henter frisk sha og prøver igen…")
                    time.sleep(_BACKOFF_SEC * (attempt + 1))
                    continue
                _note_api_failure(e)
                _log(f"[github_store] API-skrivning af {path} fejlede: HTTP {e.code} {e.reason}")
                break
            except Exception as e:
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(_BACKOFF_SEC * (attempt + 1))
                    continue
                _note_api_failure(e)
                _log(f"[github_store] API-skrivning af {path} fejlede: {e}")
                break

    if not _fallback_enabled():
        # GitHub Actions: en fejlet skrivning ER en fejl — ingen stille staging.
        _log(f"[github_store] FEJL ved skrivning af {path} (ingen lokal fallback i Actions)")
        return False

    # Offline / intet token / API-skrivning fejlede: gem lokalt + registrér.
    if not _write_local(path, data):
        return False
    _mark_pending(path, message)
    _announce_offline("api.github.com utilgængeligt eller intet token.")
    _log(
        f"[github_store] {path} skrevet LOKALT og registreret som pending.\n"
        f"[github_store] Push til main via MCP: mcp__github__push_files("
        f"owner='Poulsen4988', repo='trading-bot-dashboard', branch='main', ...)"
    )
    return False


def list_dir(path: str) -> list[str]:
    """Filnavne i en repo-mappe. API først, ellers det lokale klon."""
    if _api_available():
        url = f"{API_BASE}/{path}"
        req = urllib.request.Request(url, headers=_headers())
        try:
            with _urlopen_retry(req) as r:
                data = json.loads(r.read())
            _note_api_success()
            if isinstance(data, list):
                return [f.get("name", "") for f in data if f.get("name")]
            return []
        except urllib.error.HTTPError as e:
            if e.code == 404:
                _note_api_success()
                return []
            _note_api_failure(e)
            _log(f"[github_store] API-fejl ved listning af {path}: HTTP {e.code}")
        except Exception as e:
            _note_api_failure(e)
            _log(f"[github_store] Netværksfejl ved listning af {path}: {e}")
        if not _fallback_enabled():
            return []
    try:
        return sorted(os.listdir(_local_path(path)))
    except FileNotFoundError:
        return []


if __name__ == "__main__":
    # `python github_store.py`          → pending-liste (JSON på stdout)
    # `python github_store.py --clear`  → tøm manifestet efter vellykket MCP-push
    if "--clear" in sys.argv[1:]:
        n = clear_all_pending()
        print(json.dumps({"cleared": n}, ensure_ascii=False))
    else:
        pending = pending_writes()
        print(json.dumps({
            "repo": REPO,
            "repo_root": REPO_ROOT,
            "pending_count": len(pending),
            "pending": pending,
            "hint": (
                "Push disse filer til branch 'main' i ét commit via MCP-værktøjet "
                "mcp__github__push_files (owner='Poulsen4988', repo='trading-bot-dashboard'). "
                "Læs hver fils indhold fra det lokale klon. Kør derefter "
                "`python github_store.py --clear`."
            ) if pending else "Ingen pending skrivninger — alt er på GitHub.",
        }, ensure_ascii=False, indent=2))
