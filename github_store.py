"""
Lille GitHub content-store helper til Claude routines.

Bruger GITHUB_TOKEN eller DASHBOARD_PAT fra environment. Ingen tokens må
hardcodes i kode eller prompts.
"""
from __future__ import annotations

import base64
import json
import os
import urllib.request
from typing import Any

REPO = os.environ.get("DASHBOARD_REPO", "Poulsen4988/trading-bot-dashboard")
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("DASHBOARD_PAT") or ""
API_BASE = f"https://api.github.com/repos/{REPO}/contents"


def _headers() -> dict[str, str]:
    headers = {"User-Agent": "TradingBot/1.0"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    return headers


def get_json(path: str, default: Any = None) -> tuple[Any, str | None]:
    url = f"{API_BASE}/{path}"
    req = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(req) as r:
            payload = json.loads(r.read())
        content = base64.b64decode(payload["content"]).decode("utf-8")
        return json.loads(content), payload.get("sha")
    except Exception:
        return default, None


def put_json(path: str, data: Any, message: str) -> bool:
    if not TOKEN:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[github_store] Ingen token; gemte lokalt: {path}")
        return False

    _, sha = get_json(path, default=None)
    content = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    body = {
        "message": message,
        "content": base64.b64encode(content).decode("ascii"),
    }
    if sha:
        body["sha"] = sha

    url = f"{API_BASE}/{path}"
    headers = {**_headers(), "Content-Type": "application/json"}
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="PUT", headers=headers)
    with urllib.request.urlopen(req) as r:
        print(f"[github_store] Gemte {path} (HTTP {r.status})")
    return True
