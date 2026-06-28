"""
Lille GitHub content-store helper til Claude routines.

Bruger GITHUB_TOKEN eller DASHBOARD_PAT fra environment. Ingen tokens må
hardcodes i kode eller prompts.

Alle netværkskald har retry med backoff. put_json håndterer 409 (sha-konflikt)
ved at hente frisk sha og prøve igen, så samtidige skrivninger ikke taber data.
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
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
            # 409 (sha-konflikt) og 422 håndteres af kalderen — retry ikke her.
            if e.code not in retry_status:
                raise
        except urllib.error.URLError as e:
            last_err = e
        if attempt < _MAX_RETRIES - 1:
            time.sleep(_BACKOFF_SEC * (attempt + 1))
    raise last_err


def _local_path(path: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), path)


class GitHubReadError(RuntimeError):
    """Hævet når en read fejler og kalderen bad om raise_on_error."""


def get_json(path: str, default: Any = None, raise_on_error: bool = False) -> tuple[Any, str | None]:
    """Hent JSON fra repoet. Returnerer (data, sha).

    raise_on_error=True: hæv GitHubReadError ved ægte API-/netværksfejl (ikke 404),
    så kritiske kald (fx data.json i paper_trader) ikke fortsætter på forældede/
    tomme data og overskriver god remote-state. 404 giver altid (default, None)."""
    url = f"{API_BASE}/{path}"
    req = urllib.request.Request(url, headers=_headers())
    try:
        with _urlopen_retry(req) as r:
            payload = json.loads(r.read())
        content = base64.b64decode(payload["content"]).decode("utf-8")
        return json.loads(content), payload.get("sha")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            # Filen findes ikke endnu — gyldig tilstand, brug default.
            return default, None
        # Rigtig API-fejl. Fald IKKE tilbage til (potentielt forældet) lokal fil
        # når vi har et token — log og returnér default (eller hæv), så kalderen
        # ikke handler på gamle data og overskriver god remote-state.
        print(f"[github_store] API-fejl ved læsning af {path}: HTTP {e.code} {e.reason}")
        if raise_on_error:
            raise GitHubReadError(f"{path}: HTTP {e.code} {e.reason}") from e
        if TOKEN:
            return default, None
    except Exception as e:
        print(f"[github_store] Netværksfejl ved læsning af {path}: {e}")
        if raise_on_error:
            raise GitHubReadError(f"{path}: {e}") from e
        if TOKEN:
            return default, None

    # Ingen token (offline/lokal kørsel): læs lokal kopi hvis den findes.
    try:
        with open(_local_path(path), encoding="utf-8") as f:
            return json.load(f), None
    except Exception:
        return default, None


def put_json(path: str, data: Any, message: str) -> bool:
    if not TOKEN:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[github_store] Ingen token; gemte lokalt: {path}")
        return False

    content = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    b64 = base64.b64encode(content).decode("ascii")
    url = f"{API_BASE}/{path}"
    headers = {**_headers(), "Content-Type": "application/json"}

    # Op til _MAX_RETRIES forsøg; ved 409 (sha flyttede sig pga. samtidig skriver)
    # hentes frisk sha og forsøget gentages.
    for attempt in range(_MAX_RETRIES):
        _, sha = get_json(path, default=None)
        body = {"message": message, "content": b64}
        if sha:
            body["sha"] = sha
        req = urllib.request.Request(
            url, data=json.dumps(body).encode("utf-8"), method="PUT", headers=headers
        )
        try:
            with urllib.request.urlopen(req) as r:
                print(f"[github_store] Gemte {path} (HTTP {r.status})")
            return True
        except urllib.error.HTTPError as e:
            if e.code in (409, 500, 502, 503, 504) and attempt < _MAX_RETRIES - 1:
                grund = "409 sha-konflikt" if e.code == 409 else f"HTTP {e.code} transient"
                print(f"[github_store] {grund} på {path}, henter frisk sha og prøver igen…")
                time.sleep(_BACKOFF_SEC * (attempt + 1))
                continue
            print(f"[github_store] FEJL ved skrivning af {path}: HTTP {e.code} {e.reason}")
            return False
        except Exception as e:
            if attempt < _MAX_RETRIES - 1:
                time.sleep(_BACKOFF_SEC * (attempt + 1))
                continue
            print(f"[github_store] FEJL ved skrivning af {path}: {e}")
            return False
    return False
