"""
Lille GitHub content-store helper til Claude routines og GitHub Actions.

Bruger GITHUB_TOKEN eller DASHBOARD_PAT fra environment. Ingen tokens må
hardcodes i kode eller prompts.

VIGTIGT — to driftstilstande:

1) ONLINE (GitHub Actions, lokal kørsel med token): læs/skriv direkte via
   api.github.com Contents API. Retry med backoff; put_json håndterer 409
   (sha-konflikt) ved at hente frisk sha og prøve igen.

2) OFFLINE / SANDKASSE (Claude Code Routines): api.github.com er ofte
   blokeret af egress-proxyen (HTTP 403 "GitHub access is not enabled for
   this session"). Derfor:
   - Læsninger falder tilbage til det lokale repo-klon (rutinens sandkasse
     kloner main frisk ved sessionstart, så lokale filer er aktuelle).
   - Skrivninger gemmes lokalt i klonen OG registreres i pending-manifestet
     ".github_store_pending.json" i repo-roden. Rutinen SKAL til sidst pushe
     de pending filer til main via GitHub MCP-værktøjet
     mcp__github__push_files (owner=Poulsen4988, repo=trading-bot-dashboard,
     branch=main). Kør `python github_store.py` for at se pending-listen.
   - Sæt GITHUB_STORE_OFFLINE=1 for at tvinge offline-tilstand (spring API
     helt over — deterministisk i rutine-sandkassen).
   - En circuit breaker slår automatisk over i offline-tilstand efter
     401/403 fra API'et eller gentagne netværksfejl, så en blokeret session
     ikke spilder minutter på dømte retries.

Læsninger i samme session ser altid egne skrivninger: get_json tjekker
pending-manifestet FØR API'et, og put_json skriver altid filen lokalt
(write-through), også når API-skrivningen lykkes.

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

# Circuit breaker: efter så mange fejlende API-kald i træk skiftes der
# permanent (for processen) til offline-tilstand.
_BREAKER_THRESHOLD = 2


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

_api_down = os.environ.get("GITHUB_STORE_OFFLINE", "") not in ("", "0")
_api_fail_streak = 0
_offline_announced = False


class GitHubReadError(RuntimeError):
    """Hævet når en read fejler og kalderen bad om raise_on_error."""


def _announce_offline(reason: str) -> None:
    global _offline_announced
    if _offline_announced:
        return
    _offline_announced = True
    print(
        f"[github_store] OFFLINE-TILSTAND: {reason}\n"
        f"[github_store] Læsninger bruger det lokale repo-klon; skrivninger gemmes\n"
        f"[github_store] lokalt og registreres i {os.path.basename(PENDING_MANIFEST)}.\n"
        f"[github_store] HUSK til sidst: push pending filer til branch main via\n"
        f"[github_store] MCP-værktøjet mcp__github__push_files "
        f"(kør `python github_store.py` for listen)."
    )


def _trip_breaker(reason: str) -> None:
    global _api_down
    _api_down = True
    _announce_offline(reason)


def _note_api_failure(err: Exception) -> None:
    """Registrér et fejlet API-kald og slå evt. circuit breakeren til."""
    global _api_fail_streak
    if isinstance(err, urllib.error.HTTPError) and err.code in (401, 403):
        # Auth/policy-fejl (fx proxyens "GitHub access is not enabled for this
        # session" eller revoked token) heler ikke af sig selv.
        _trip_breaker(f"api.github.com afviste kaldet (HTTP {err.code}).")
        return
    _api_fail_streak += 1
    if _api_fail_streak >= _BREAKER_THRESHOLD:
        _trip_breaker(f"{_api_fail_streak} API-kald fejlede i træk ({err}).")


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
        print(f"[github_store] Kunne ikke læse lokal {path}: {e}")
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
        print(f"[github_store] FEJL: kunne ikke skrive lokal {path}: {e}")
        return False


def _load_manifest() -> dict:
    try:
        with open(PENDING_MANIFEST, encoding="utf-8") as f:
            m = json.load(f)
        if isinstance(m, dict) and isinstance(m.get("pending"), dict):
            return m
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[github_store] Kunne ikke læse pending-manifest: {e}")
    return {"version": 1, "pending": {}}


def _save_manifest(m: dict) -> None:
    try:
        tmp = PENDING_MANIFEST + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=2)
        os.replace(tmp, PENDING_MANIFEST)
    except Exception as e:
        print(f"[github_store] FEJL: kunne ikke opdatere pending-manifest: {e}")


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
    3. Lokalt repo-klon som fallback ved API-fejl eller offline-tilstand.

    raise_on_error=True: hæv GitHubReadError hvis hverken API eller lokal
    læsning kan levere filen pga. fejl (404 giver stadig (default, None)),
    så kritiske kald (fx data.json i paper_trader) ikke handler mod tom state.
    """
    # 1) Egen usendt skrivning fra denne session vinder altid.
    if is_pending(path):
        found, data = _read_local(path)
        if found:
            return data, None

    api_error: Exception | None = None
    if TOKEN and not _api_down:
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
            print(f"[github_store] API-fejl ved læsning af {path}: HTTP {e.code} {e.reason} — prøver lokalt klon")
        except Exception as e:
            api_error = e
            _note_api_failure(e)
            print(f"[github_store] Netværksfejl ved læsning af {path}: {e} — prøver lokalt klon")

    # 3) Lokalt klon (offline-tilstand, intet token, eller API-fejl ovenfor).
    found, data = _read_local(path)
    if found:
        return data, None

    if raise_on_error and api_error is not None:
        raise GitHubReadError(f"{path}: {api_error}") from api_error
    if raise_on_error and TOKEN and _api_down:
        raise GitHubReadError(f"{path}: API i offline-tilstand og ingen lokal kopi")
    return default, None


def put_json(path: str, data: Any, message: str) -> bool:
    """Skriv JSON. Returnerer True hvis filen ER på GitHub, False hvis den kun
    blev gemt lokalt (registreret i pending-manifestet og skal pushes via MCP).
    """
    if TOKEN and not _api_down:
        content = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        b64 = base64.b64encode(content).decode("ascii")
        url = f"{API_BASE}/{path}"
        headers = {**_headers(), "Content-Type": "application/json"}

        # Op til _MAX_RETRIES forsøg; ved 409 (sha flyttede sig pga. samtidig
        # skriver) hentes frisk sha og forsøget gentages.
        for attempt in range(_MAX_RETRIES):
            sha = None
            try:
                head = urllib.request.Request(url, headers=_headers())
                with urllib.request.urlopen(head) as r:
                    sha = json.loads(r.read()).get("sha")
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    _note_api_failure(e)
                    if _api_down:
                        break
            except Exception as e:
                _note_api_failure(e)
                if _api_down:
                    break

            body = {"message": message, "content": b64}
            if sha:
                body["sha"] = sha
            req = urllib.request.Request(
                url, data=json.dumps(body).encode("utf-8"), method="PUT", headers=headers
            )
            try:
                with urllib.request.urlopen(req) as r:
                    print(f"[github_store] Gemte {path} (HTTP {r.status})")
                _note_api_success()
                # Write-through: hold det lokale klon i synk, så senere læsninger
                # i samme session ser den nye fil selv hvis API'et falder ud.
                _write_local(path, data)
                _clear_pending(path)
                return True
            except urllib.error.HTTPError as e:
                if e.code in (409, 500, 502, 503, 504) and attempt < _MAX_RETRIES - 1:
                    grund = "409 sha-konflikt" if e.code == 409 else f"HTTP {e.code} transient"
                    print(f"[github_store] {grund} på {path}, henter frisk sha og prøver igen…")
                    time.sleep(_BACKOFF_SEC * (attempt + 1))
                    continue
                _note_api_failure(e)
                print(f"[github_store] API-skrivning af {path} fejlede: HTTP {e.code} {e.reason}")
                break
            except Exception as e:
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(_BACKOFF_SEC * (attempt + 1))
                    continue
                _note_api_failure(e)
                print(f"[github_store] API-skrivning af {path} fejlede: {e}")
                break

    # Offline / intet token / API-skrivning fejlede: gem lokalt + registrér.
    if not _write_local(path, data):
        return False
    _mark_pending(path, message)
    _announce_offline("api.github.com utilgængeligt eller intet token.")
    print(
        f"[github_store] {path} skrevet LOKALT og registreret som pending.\n"
        f"[github_store] Push til main via MCP: mcp__github__push_files("
        f"owner='Poulsen4988', repo='trading-bot-dashboard', branch='main', ...)"
    )
    return False


def list_dir(path: str) -> list[str]:
    """Filnavne i en repo-mappe. API først, ellers det lokale klon."""
    if TOKEN and not _api_down:
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
            print(f"[github_store] API-fejl ved listning af {path}: HTTP {e.code} — prøver lokalt klon")
        except Exception as e:
            _note_api_failure(e)
            print(f"[github_store] Netværksfejl ved listning af {path}: {e} — prøver lokalt klon")
    try:
        return sorted(os.listdir(_local_path(path)))
    except FileNotFoundError:
        return []


if __name__ == "__main__":
    # `python github_store.py` → status til rutinen: hvad mangler at blive pushet?
    pending = pending_writes()
    print(json.dumps({
        "repo": REPO,
        "repo_root": REPO_ROOT,
        "pending_count": len(pending),
        "pending": pending,
        "hint": (
            "Push disse filer til branch 'main' i ét commit via MCP-værktøjet "
            "mcp__github__push_files (owner='Poulsen4988', repo='trading-bot-dashboard'). "
            "Læs hver fils indhold fra det lokale klon. Tom liste = intet at gøre."
        ) if pending else "Ingen pending skrivninger — alt er på GitHub.",
    }, ensure_ascii=False, indent=2))
