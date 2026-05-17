"""
Synkroniserer journal.jsonl ind i data.json til GitHub Pages-dashboardet.

Dashboardet ligger på:
https://poulsen4988.github.io/trading-bot-dashboard/

Der bruges ingen Saxo- eller Gist-integration. Scriptet kan køre lokalt eller fra
en Claude routine. Hvis DASHBOARD_PAT er sat, pushes data.json til GitHub.
Ellers opdateres den lokale data.json kun.
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

GITHUB_PAT = os.environ.get("DASHBOARD_PAT") or os.environ.get("GITHUB_TOKEN") or ""
GITHUB_REPO = os.environ.get("DASHBOARD_REPO", "Poulsen4988/trading-bot-dashboard")
DASHBOARD_URL = "https://poulsen4988.github.io/trading-bot-dashboard/"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(SCRIPT_DIR, "data.json")
INITIAL_CASH = 100_000


def load_json_file(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError:
        return default


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
    reason = entry.get("reason") or entry.get("analyse") or ""
    verdict = entry.get("action", "HOLD").upper()
    return {"verdict": verdict, "summary": reason}


def entry_key(entry):
    ts = entry.get("timestamp", "")
    date = ts[:10] if ts else entry.get("date", "")
    return (
        date,
        entry.get("symbol") or entry.get("name") or "N/A",
        entry.get("action", "").upper(),
        entry.get("reason", "")[:80],
    )


def journal_to_trade(entry, next_id):
    action = entry.get("action", "").upper()
    ts = entry.get("timestamp", "")
    date = ts[:10] if ts else datetime.now(timezone.utc).strftime("%Y-%m-%d")
    amount = int(entry.get("amount") or entry.get("shares") or 0)
    price = float(entry.get("price") or 0)
    value = float(entry.get("estimated_value") or entry.get("value") or (amount * price if amount and price else 0))
    return {
        "id": next_id,
        "date": date,
        "action": action,
        "symbol": entry.get("symbol") or "N/A",
        "name": entry.get("name") or entry.get("symbol") or "N/A",
        "shares": amount,
        "price": price if price else None,
        "value": value if value else None,
        "is_new": False,
        "reasoning": build_reasoning(entry),
    }


def mark_latest_new(trades):
    for t in trades:
        t["is_new"] = False
    if trades:
        trades[-1]["is_new"] = True


def update_history(data):
    portfolio = data.setdefault("portfolio", {})
    cash = float(portfolio.get("cash", INITIAL_CASH))
    positions = portfolio.get("positions", [])
    pos_value = 0.0
    for p in positions:
        shares = float(p.get("shares") or 0)
        price = float(p.get("current_price") or p.get("purchase_price") or p.get("avg_price") or 0)
        pos_value += shares * price
    total = round(cash + pos_value, 2)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    history = data.setdefault("history", [])
    history = [h for h in history if h.get("date") != today]
    history.append({"date": today, "portfolio_value": total})
    data["history"] = history
    portfolio["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def load_latest_screening():
    """Returnerer screener-rækker for seneste screening, keyet på yf-symbol."""
    files = sorted(glob.glob(os.path.join(SCRIPT_DIR, "screening", "*.json")))
    if not files:
        return {}, None
    raw = load_json_file(files[-1], {})
    by_sym = {row.get("symbol"): row for row in raw.get("selected", [])}
    return by_sym, raw.get("date")


def build_stocks():
    try:
        from watchlist import C25
        import knowledge_manager as km
    except ImportError:
        return []

    prices_file = os.path.join(SCRIPT_DIR, "prices", "latest.json")
    raw = load_json_file(prices_file, {})
    prices = raw.get("stocks", {})
    prices_age = raw.get("fetched_at")
    screening, screening_date = load_latest_screening()

    stocks = []
    for s in C25:
        yf_sym = s["yf"]
        saxo = s["saxo"]
        pdata = prices.get(yf_sym, {})
        kb = km.load(saxo) or {}

        scr = screening.get(yf_sym)
        technical = None
        if scr:
            technical = {
                "screening_date": screening_date,
                "score": scr.get("score"),
                "rsi_proxy": scr.get("rsi_proxy"),
                "stoch_proxy": scr.get("stoch_proxy"),
                "bb_position": scr.get("bb_position"),
                "sma50_vs_price": scr.get("sma50_vs_price"),
                "sma200_vs_price": scr.get("sma200_vs_price"),
                "macd_line": scr.get("macd_line"),
                "atr": scr.get("atr"),
                "momentum_divergence": scr.get("momentum_divergence"),
                "indicator_method": scr.get("indicator_method"),
                "signals": scr.get("screening_signals", []),
                "rationale": scr.get("screening_rationale"),
            }

        stocks.append({
            "symbol": saxo,
            "name": s["name"],
            "uic": s["uic"],
            "tradeable": s["uic"] is not None,
            "price": pdata.get("price"),
            "pct_1d": pdata.get("pct_1d"),
            "pct_5d": pdata.get("pct_5d"),
            "pct_20d": pdata.get("pct_20d"),
            "pe_forward": pdata.get("pe_forward"),
            "pe_trailing": pdata.get("pe_trailing"),
            "div_yield": pdata.get("div_yield"),
            "volume_ratio": pdata.get("volume_ratio"),
            "pct_from_52w_high": pdata.get("pct_from_52w_high"),
            "pct_from_52w_low": pdata.get("pct_from_52w_low"),
            "revenue_growth": pdata.get("revenue_growth"),
            "earnings_growth": pdata.get("earnings_growth"),
            "market_cap": pdata.get("market_cap"),
            "sector": pdata.get("sector"),
            "industry": pdata.get("industry"),
            "overview": kb.get("overview", ""),
            "fin_summary": kb.get("financials", {}).get("summary", ""),
            "news": kb.get("news", [])[:8],
            "technical": technical,
            "prices_age": prices_age,
        })

    print(f"[sync_dashboard] Stocks bygget: {len(stocks)} aktier, prices_age={prices_age}")
    return stocks


def fetch_remote_sha():
    if not GITHUB_PAT:
        return None
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/data.json"
    headers = {"Authorization": f"Bearer {GITHUB_PAT}", "User-Agent": "TradingBot/1.0"}
    try:
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read()).get("sha")
    except Exception as e:
        print(f"[sync_dashboard] Kunne ikke hente remote SHA: {e}")
        return None


def push_to_github(data):
    if not GITHUB_PAT:
        print(f"[sync_dashboard] DASHBOARD_PAT mangler; lokal data.json opdateret. Dashboard: {DASHBOARD_URL}")
        return

    sha = fetch_remote_sha()
    if not sha:
        print("[sync_dashboard] Springer GitHub push over: ingen SHA fundet.")
        return

    content = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/data.json"
    headers = {
        "Authorization": f"Bearer {GITHUB_PAT}",
        "Content-Type": "application/json",
        "User-Agent": "TradingBot/1.0",
    }
    body = json.dumps({
        "message": f"Dashboard update {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "content": base64.b64encode(content).decode("ascii"),
        "sha": sha,
    }).encode("utf-8")

    try:
        req = urllib.request.Request(api_url, data=body, method="PUT", headers=headers)
        with urllib.request.urlopen(req) as r:
            print(f"[sync_dashboard] GitHub Pages data.json opdateret (HTTP {r.status})")
            print(f"[sync_dashboard] Dashboard: {DASHBOARD_URL}")
    except Exception as e:
        print(f"[sync_dashboard] GitHub push fejlede: {e}")


def sync():
    data = load_json_file(DATA_PATH, {
        "portfolio": {"initial_cash": INITIAL_CASH, "cash": INITIAL_CASH, "currency": "DKK", "positions": []},
        "history": [],
        "trades": [],
        "stocks": [],
    })

    trades = data.setdefault("trades", [])
    existing = {(t.get("date"), t.get("symbol"), t.get("action"), (t.get("reasoning") or {}).get("summary", "")[:80]) for t in trades}
    next_id = max([int(t.get("id", 0)) for t in trades] + [0]) + 1

    for entry in load_journal():
        action = entry.get("action", "").upper()
        if action not in {"BUY", "SELL", "HOLD", "REVIEW"}:
            continue
        t = journal_to_trade(entry, next_id)
        key = (t.get("date"), t.get("symbol"), t.get("action"), (t.get("reasoning") or {}).get("summary", "")[:80])
        if key in existing:
            continue
        trades.append(t)
        existing.add(key)
        next_id += 1

    mark_latest_new(trades)
    update_history(data)
    data["stocks"] = build_stocks()

    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"[sync_dashboard] {len(trades)} dashboard-events -> data.json opdateret")
    push_to_github(data)


if __name__ == "__main__":
    sync()
