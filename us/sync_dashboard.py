"""
Syncs the US paper-trading state into us/data.json for the GitHub Pages dashboard.

Dashboard lives at:
https://poulsen4988.github.io/trading-bot-dashboard/

No Saxo/Gist integration. Runs locally or from a Claude routine. If DASHBOARD_PAT
is set, data.json is pushed to GitHub; otherwise only the local copy is updated.

Sole-writer discipline: paper_trader.py owns portfolio/trades/history. sync only
writes the derived keys (stocks, benchmarks, sector_exposure_pct, latest_decisions)
and fills in today's history point ONLY if it is missing.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import base64
import glob
import json
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
INITIAL_CASH = 100_000  # USD


def load_json_file(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError:
        return default


def update_history(data):
    """Appends today's portfolio point - ONLY if it is missing.

    paper_trader.py is the authoritative writer of history (post-trade value).
    sync therefore never overwrites an existing point; it only fills days where
    the trade routine did not run, so the two writers cannot diverge."""
    portfolio = data.setdefault("portfolio", {})
    portfolio["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    history = data.setdefault("history", [])
    if any(h.get("date") == today for h in history):
        return
    cash = float(portfolio.get("cash", INITIAL_CASH))
    pos_value = 0.0
    for p in portfolio.get("positions", []):
        shares = float(p.get("shares") or 0)
        price = float(p.get("current_price") or p.get("purchase_price") or p.get("avg_price") or 0)
        pos_value += shares * price
    history.append({"date": today, "portfolio_value": round(cash + pos_value, 2)})


def list_github_dir(path):
    """Lists files in a GitHub dir. Returns list of dicts with 'name'/'path'."""
    if not GITHUB_PAT:
        return []
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    headers = {"Authorization": f"Bearer {GITHUB_PAT}", "User-Agent": "TradingBot/1.0"}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as r:
            data = json.loads(r.read())
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"[sync_dashboard] Could not list {path}: {e}")
        return []


def fetch_github_json(path):
    """Fetches a JSON file from GitHub via the Contents API."""
    if not GITHUB_PAT:
        return None
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    headers = {"Authorization": f"Bearer {GITHUB_PAT}", "User-Agent": "TradingBot/1.0"}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as r:
            payload = json.loads(r.read())
        content = base64.b64decode(payload["content"]).decode("utf-8")
        return json.loads(content)
    except Exception as e:
        print(f"[sync_dashboard] Could not fetch {path}: {e}")
        return None


def latest_json_from_dir(github_path, local_subdir):
    """Finds the latest YYYY-MM-DD.json - first via GitHub, falls back to local dir."""
    listing = list_github_dir(github_path)
    json_files = sorted(
        [f for f in listing if f.get("name", "").endswith(".json")],
        key=lambda f: f["name"], reverse=True,
    )
    if json_files:
        latest = json_files[0]["name"]
        data = fetch_github_json(f"{github_path}/{latest}")
        if data is not None:
            return data, latest.replace(".json", "")

    files = sorted(glob.glob(os.path.join(SCRIPT_DIR, local_subdir, "*.json")))
    if files:
        raw = load_json_file(files[-1], {})
        date_str = os.path.basename(files[-1]).replace(".json", "")
        return raw, date_str
    return {}, None


def load_latest_screening():
    """Returns screener rows for the latest screening, keyed on yf symbol.

    US screening schema stores scored rows in `scored` (each with a `symbol`)."""
    raw, date_str = latest_json_from_dir("us/screening", "screening")
    by_sym = {row.get("symbol"): row for row in (raw or {}).get("scored", [])}
    return by_sym, (raw or {}).get("date") or date_str


def load_latest_analysis():
    """Returns agent analysis for the latest analysis file, keyed on yf symbol."""
    raw, date_str = latest_json_from_dir("us/analysis", "analysis")
    return (raw or {}).get("stocks", {}), (raw or {}).get("date") or date_str


def load_latest_decisions():
    """Returns today's AI decisions (BUY/SELL/HOLD with reasoning)."""
    raw, date_str = latest_json_from_dir("us/decisions", "decisions")
    if not raw:
        return None
    return {
        "date": raw.get("date") or date_str,
        "market_summary": raw.get("market_summary"),
        "decisions": raw.get("decisions", []),
    }


def load_benchmarks():
    """Fetches us/prices/benchmarks.json from GitHub (falls back to local)."""
    data = fetch_github_json("us/prices/benchmarks.json")
    if data is None:
        data = load_json_file(os.path.join(SCRIPT_DIR, "prices", "benchmarks.json"), {})
    return data or {}


def build_benchmark_series(portfolio_history, benchmarks_raw, initial_cash):
    """Builds benchmark history normalized to the same start value as the portfolio.

    Returns list of {ticker, label, color, history: [{date, portfolio_value}]}
    so the chart can plot directly alongside existing portfolio history.
    """
    if not portfolio_history or not benchmarks_raw:
        return []

    start_date = portfolio_history[0].get("date")
    history_dates = {h.get("date") for h in portfolio_history if h.get("date")}
    benchmarks = (benchmarks_raw or {}).get("benchmarks", {})

    colors = {
        "^GSPC": "#e3b341",
        "^NDX": "#a371f7",
    }

    out = []
    for ticker, info in benchmarks.items():
        if "error" in (info or {}):
            continue
        hist = (info or {}).get("history", [])
        by_date = {h.get("date"): h.get("close") for h in hist}

        # Find benchmark close on (or just after) portfolio start_date
        start_close = None
        if start_date and start_date in by_date:
            start_close = by_date[start_date]
        else:
            sorted_dates = sorted(by_date.keys())
            for d in sorted_dates:
                if start_date is None or d >= start_date:
                    start_close = by_date[d]
                    break
        if not start_close:
            continue

        # Build series on portfolio dates (skip days without benchmark close)
        series = []
        for hd in sorted(history_dates):
            close = by_date.get(hd)
            if close is None:
                # find latest available earlier date
                earlier = [d for d in by_date if d <= hd]
                if earlier:
                    close = by_date[max(earlier)]
            if close:
                value = round(initial_cash * close / start_close, 2)
                series.append({"date": hd, "portfolio_value": value})

        out.append({
            "ticker": ticker,
            "label": (info or {}).get("label", "S&P 500" if ticker == "^GSPC" else ticker),
            "color": colors.get(ticker, "#8b949e"),
            "history": series,
        })
    return out


def compute_sector_exposure(positions):
    """Sector breakdown as percent of total position value.

    Positions use yf symbols ("AAPL"); watchlist.YF_TO_SECTOR maps yf -> sector
    directly (no saxo indirection)."""
    try:
        from watchlist import YF_TO_SECTOR
    except Exception:
        YF_TO_SECTOR = {}

    sectors = {}
    total_val = 0.0
    for p in positions or []:
        shares = float(p.get("shares") or 0)
        price = float(p.get("current_price") or p.get("purchase_price") or 0)
        val = shares * price
        if val <= 0:
            continue
        sec = YF_TO_SECTOR.get(p.get("symbol")) or "Unknown"
        sectors[sec] = sectors.get(sec, 0.0) + val
        total_val += val
    if total_val <= 0:
        return {}
    return {k: round(v / total_val * 100, 1) for k, v in sectors.items()}


def build_stocks():
    try:
        from watchlist import SP500
        import knowledge_manager as km
    except ImportError:
        return []

    raw = fetch_github_json("us/prices/latest.json") or load_json_file(
        os.path.join(SCRIPT_DIR, "prices", "latest.json"), {})
    prices = raw.get("stocks", {})
    prices_age = raw.get("fetched_at")
    screening, screening_date = load_latest_screening()
    analysis_map, analysis_date = load_latest_analysis()

    # US universe is ~503 tickers — only surface the bot's actual focus on the
    # dashboard: current holdings + today's deep-analysed set + top screener ranks.
    TOP_N = 30
    held = set()
    try:
        _dd = fetch_github_json("us/data.json") or {}
        held = {p.get("symbol") for p in _dd.get("portfolio", {}).get("positions", []) if p.get("symbol")}
    except Exception:
        held = set()
    _ranked = sorted(screening.items(), key=lambda kv: (kv[1].get("score") or -1), reverse=True)
    keep = held | set(analysis_map.keys()) | {sym for sym, _ in _ranked[:TOP_N]}

    stocks = []
    for s in SP500:
        yf_sym = s["yf"]
        if keep and yf_sym not in keep:
            continue
        pdata = prices.get(yf_sym, {})
        kb = km.load(yf_sym) or {}

        adata = analysis_map.get(yf_sym)
        analysis = None
        if adata:
            analysis = {
                "analysis_date": analysis_date,
                "tier": adata.get("tier"),
                "verdict": adata.get("verdict"),
                "confidence": adata.get("confidence"),
                "bull": adata.get("bull", []),
                "bear": adata.get("bear", []),
                "summary": adata.get("summary"),
                "key_risk": adata.get("key_risk"),
            }

        scr = screening.get(yf_sym)
        technical = None
        if scr:
            technical = {
                "screening_date": screening_date,
                "score": scr.get("score"),
                "rsi": scr.get("rsi"),
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
            "symbol": yf_sym,
            "name": s["name"],
            "tradeable": True,
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
            "sector": pdata.get("sector") or s.get("sector"),
            "industry": pdata.get("industry"),
            "next_earnings_date": pdata.get("next_earnings_date"),
            "overview": kb.get("overview", ""),
            "fin_summary": kb.get("financials", {}).get("summary", ""),
            "news": kb.get("news", [])[:8],
            "technical": technical,
            "analysis": analysis,
            "prices_age": prices_age,
        })

    print(f"[sync_dashboard] Stocks built: {len(stocks)} stocks, prices_age={prices_age}")
    return stocks


def sync():
    import github_store

    default = {
        "portfolio": {"initial_cash": INITIAL_CASH, "cash": INITIAL_CASH, "currency": "USD", "positions": []},
        "history": [],
        "trades": [],
        "stocks": [],
    }
    # Read fresh from GitHub so the dashboard is built on top of paper_trader's
    # latest portfolio/trades. Fall back to local checkout without a token.
    # IMPORTANT: a failing remote read must NEVER fall back to an empty default
    # and get written back - that reset the DK portfolio 2026-07-17. With a
    # token: read failure => abort the whole sync (no write).
    data = None
    if github_store.TOKEN:
        data, _ = github_store.get_json("us/data.json", default=None, raise_on_error=True)
    if not data:
        data = load_json_file(DATA_PATH, default)

    # trades + portfolio are owned by paper_trader.py - sync does not touch them.
    data.setdefault("trades", [])

    update_history(data)
    data["stocks"] = build_stocks()
    data["latest_decisions"] = load_latest_decisions()

    initial_cash = float(data.get("portfolio", {}).get("initial_cash", INITIAL_CASH))
    data["benchmarks"] = build_benchmark_series(
        data.get("history", []), load_benchmarks(), initial_cash,
    )
    data["sector_exposure_pct"] = compute_sector_exposure(
        data.get("portfolio", {}).get("positions", []),
    )

    # Write locally (GitHub Actions' git step commits it) and push via
    # github_store (retry + 409-handling).
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"[sync_dashboard] {len(data.get('trades', []))} trades, {len(data.get('stocks', []))} stocks -> us/data.json")
    github_store.put_json("us/data.json", data, f"Dashboard update {ts}")
    print(f"[sync_dashboard] Dashboard: {DASHBOARD_URL}")


if __name__ == "__main__":
    sync()
