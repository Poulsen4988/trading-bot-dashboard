"""
Læser alle journal*.jsonl-filer og fletter med eksisterende GitHub-data.
Pusher til GitHub Pages repo så dashboardet er tilgængeligt overalt.
Køres af bot.py efter hver beslutning.
"""
import base64
import glob
import json
import os
import urllib.request
from datetime import datetime, timezone

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

GITHUB_PAT = os.environ.get("DASHBOARD_PAT", "")
GITHUB_REPO = "poulsen4988/trading-bot-dashboard"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INITIAL_CASH = 100_000


def load_journal():
    entries = []
    pattern = os.path.join(SCRIPT_DIR, "journal*.jsonl")
    for path in sorted(glob.glob(pattern)):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    entries.sort(key=lambda e: e.get("timestamp", ""))
    return entries


def build_reasoning(entry):
    existing = entry.get("reasoning")
    if isinstance(existing, dict):
        return existing
    reason = entry.get("reason") or ""
    if not reason:
        return {}
    action = entry.get("action", "HOLD").upper()
    verdict = {"BUY": "KØB", "SELL": "SÆLG"}.get(action, "HOLD")
    return {"verdict": verdict, "summary": reason}


def fetch_github_data():
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/data.json"
    headers = {"Authorization": f"Bearer {GITHUB_PAT}", "User-Agent": "TradingBot/1.0"}
    try:
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req) as r:
            response = json.loads(r.read())
        content = base64.b64decode(response["content"]).decode("utf-8")
        return json.loads(content), response["sha"]
    except Exception as e:
        print(f"[sync_dashboard] Kunne ikke hente GitHub-data: {e}")
        return None, None


def sync():
    entries = load_journal()

    # Byg lokale handler fra journal
    local_trades = []
    for entry in entries:
        action = entry.get("action", "").upper()
        ts = entry.get("timestamp", "")
        date = ts[:10] if ts else ""
        if action not in ("BUY", "SELL", "HOLD"):
            continue
        symbol = entry.get("symbol") or "N/A"
        amount = int(entry.get("amount") or 0)
        price = float(entry.get("price") or 0)
        local_trades.append({
            "_key": (date, symbol, action),
            "action": action,
            "symbol": symbol,
            "name": symbol,
            "date": date,
            "shares": amount if amount else None,
            "price": price if price else None,
            "value": amount * price if amount and price else None,
            "reasoning": build_reasoning(entry),
            "is_new": False,
        })

    # Hent eksisterende GitHub-data og flet
    github_data, sha = fetch_github_data()

    if github_data:
        # Start med eksisterende GitHub-handler, giv dem numeriske ID'er
        merged = []
        for i, t in enumerate(github_data.get("trades", []), start=1):
            t["id"] = i
            t["is_new"] = False
            merged.append(t)

        # Tilføj nye lokale handler der ikke allerede er i GitHub-data
        existing_keys = {(t["date"], t["symbol"], t["action"]) for t in merged}
        next_id = len(merged) + 1
        for t in local_trades:
            if t["_key"] not in existing_keys:
                del t["_key"]
                t["id"] = next_id
                merged.append(t)
                next_id += 1

        portfolio = github_data.get("portfolio", {})
        portfolio["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        history = github_data.get("history", [])
    else:
        # Fallback: brug kun lokale data
        merged = []
        for i, t in enumerate(local_trades, start=1):
            del t["_key"]
            t["id"] = i
            merged.append(t)
        portfolio = {"initial_cash": INITIAL_CASH, "cash": INITIAL_CASH, "currency": "DKK",
                     "positions": [], "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
        history = [{"date": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "portfolio_value": INITIAL_CASH}]
        sha = None

    if merged:
        merged[-1]["is_new"] = True

    data = {"portfolio": portfolio, "history": history, "trades": merged}

    out_path = os.path.join(SCRIPT_DIR, "dashboard", "data.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"[sync_dashboard] {len(merged)} handler -> data.json opdateret")
    push_to_github(data, sha)


def push_to_github(data, sha=None):
    content = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/data.json"
    headers = {
        "Authorization": f"Bearer {GITHUB_PAT}",
        "Content-Type": "application/json",
        "User-Agent": "TradingBot/1.0",
    }

    if not sha:
        try:
            req = urllib.request.Request(api_url, headers=headers)
            with urllib.request.urlopen(req) as r:
                sha = json.loads(r.read())["sha"]
        except Exception as e:
            print(f"[sync_dashboard] GitHub: kunne ikke hente SHA: {e}")
            return

    body = json.dumps({
        "message": f"Bot update {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "content": base64.b64encode(content).decode("ascii"),
        "sha": sha,
    }).encode("utf-8")

    try:
        req = urllib.request.Request(api_url, data=body, method="PUT", headers=headers)
        with urllib.request.urlopen(req) as r:
            print(f"[sync_dashboard] GitHub Pages opdateret (status {r.status})")
    except Exception as e:
        print(f"[sync_dashboard] GitHub push fejlede: {e}")


if __name__ == "__main__":
    sync()
