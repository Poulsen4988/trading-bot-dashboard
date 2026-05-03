"""
Kør dette script om morgenen inden markedet åbner (kl. 8:30).
Det holder Saxo-tokenet frisk ved at forny det lokalt hvert 14. minut
og pushe det til GitHub Gist, så cloud-routinerne kan bruge det.

Kommando: python token_keeper.py
Stop med Ctrl+C når dagen er slut.
"""
import json
import os
import time
import urllib.request
import urllib.parse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOKENS_FILE = os.path.join(SCRIPT_DIR, "tokens.json")
REFRESH_INTERVAL = 14 * 60  # 14 minutter

# Indlæs .env hvis den findes (lokale kørsler)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(SCRIPT_DIR, ".env"))
except ImportError:
    pass

GITHUB_PAT = os.environ.get("GIST_PAT", "")
GIST_ID = os.environ.get("GIST_ID", "")
APP_KEY = os.environ.get("SAXO_APP_KEY", "")
APP_SECRET = os.environ.get("SAXO_APP_SECRET", "")
TOKEN_URL = os.environ.get("SAXO_TOKEN_URL", "https://sim.logonvalidation.net/token")


def load_tokens():
    with open(TOKENS_FILE, encoding="utf-8") as f:
        return json.load(f)


def refresh_token(refresh_token_value):
    data = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token_value,
        "client_id": APP_KEY,
        "client_secret": APP_SECRET,
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=data)
    with urllib.request.urlopen(req, timeout=10) as r:
        new_tokens = json.loads(r.read())
    if "access_token" not in new_tokens:
        raise Exception(f"Token refresh fejlede: {new_tokens}")
    new_tokens["issued_at"] = time.time()
    return new_tokens


def save_tokens_local(tokens):
    with open(TOKENS_FILE, "w", encoding="utf-8") as f:
        json.dump(tokens, f, indent=2)


def push_to_gist(tokens):
    body = json.dumps({
        "files": {
            "tokens.json": {"content": json.dumps(tokens, indent=2)}
        }
    }).encode()
    req = urllib.request.Request(
        f"https://api.github.com/gists/{GIST_ID}",
        data=body,
        method="PATCH",
        headers={
            "Authorization": f"Bearer {GITHUB_PAT}",
            "Content-Type": "application/json",
            "User-Agent": "TradingBot/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status


def main():
    print("=== Token Keeper startet ===")
    print(f"Fornyer tokens lokalt hvert {REFRESH_INTERVAL // 60} minutter og pusher til Gist.")
    print("Stop med Ctrl+C\n")

    while True:
        try:
            tokens = load_tokens()
            new_tokens = refresh_token(tokens["refresh_token"])
            save_tokens_local(new_tokens)
            status = push_to_gist(new_tokens)
            issued = time.strftime("%H:%M:%S")
            print(f"[{issued}] Token fornyet og pushet til Gist (HTTP {status})")
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] FEJL: {e}")

        time.sleep(REFRESH_INTERVAL)


if __name__ == "__main__":
    main()
