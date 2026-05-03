"""
Pusher tokens.json til GitHub Gist så GitHub Actions kan hente dem.
Kørsel: python gist_update.py
Credentials læses fra env vars: GIST_PAT og GIST_ID.
"""
import json
import os
import urllib.request

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

GIST_ID = os.environ.get("GIST_ID", "")
GIST_PAT = os.environ.get("GIST_PAT", "")
TOKENS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tokens.json")


def main():
    with open(TOKENS_FILE, encoding="utf-8") as f:
        tokens_content = f.read()

    body = json.dumps({
        "files": {"tokens.json": {"content": tokens_content}}
    }).encode()

    req = urllib.request.Request(
        f"https://api.github.com/gists/{GIST_ID}",
        data=body, method="PATCH",
        headers={
            "Authorization": f"Bearer {GIST_PAT}",
            "Content-Type": "application/json",
            "User-Agent": "TradingBot/1.0",
        },
    )
    with urllib.request.urlopen(req) as r:
        print(f"Tokens pushet til Gist (status {r.status})")


if __name__ == "__main__":
    main()
