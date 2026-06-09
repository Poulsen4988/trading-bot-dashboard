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


def update_history(data):
    """Tilføjer dagens porteføljepunkt — KUN hvis det mangler.

    paper_trader.py er autoritativ skriver af history (post-handel-værdi). Sync
    overskriver derfor ikke et eksisterende punkt; den udfylder kun dage hvor
    handels-rutinen ikke har kørt, så de to skrivere ikke divergerer."""
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
    """Lister filer i en mappe på GitHub. Returns list of dicts med 'name'/'path'."""
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
        print(f"[sync_dashboard] Kunne ikke liste {path}: {e}")
        return []


def fetch_github_json(path):
    """Henter en JSON-fil fra GitHub via Contents API."""
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
        print(f"[sync_dashboard] Kunne ikke hente {path}: {e}")
        return None


def latest_json_from_dir(github_path, local_subdir):
    """Finder seneste YYYY-MM-DD.json — først via GitHub, falder tilbage til lokal mappe."""
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
    """Returnerer screener-rækker for seneste screening, keyet på yf-symbol."""
    raw, date_str = latest_json_from_dir("screening", "screening")
    by_sym = {row.get("symbol"): row for row in (raw or {}).get("selected", [])}
    return by_sym, (raw or {}).get("date") or date_str


def load_latest_analysis():
    """Returnerer agent-analyse for seneste analysis-fil, keyet på yf-symbol."""
    raw, date_str = latest_json_from_dir("analysis", "analysis")
    return (raw or {}).get("stocks", {}), (raw or {}).get("date") or date_str


def load_latest_decisions():
    """Returnerer dagens AI-beslutninger (BUY/SELL/HOLD med reasoning)."""
    raw, date_str = latest_json_from_dir("decisions", "decisions")
    if not raw:
        return None
    return {
        "date": raw.get("date") or date_str,
        "market_summary": raw.get("market_summary"),
        "decisions": raw.get("decisions", []),
    }


def load_benchmarks():
    """Henter prices/benchmarks.json fra GitHub (fallback til lokalt)."""
    data = fetch_github_json("prices/benchmarks.json")
    if data is None:
        data = load_json_file(os.path.join(SCRIPT_DIR, "prices", "benchmarks.json"), {})
    return data or {}


def build_benchmark_series(portfolio_history, benchmarks_raw, initial_cash):
    """Bygger benchmark-historik normaliseret til samme startværdi som porteføljen.

    Returnerer liste af {ticker, label, color, history: [{date, portfolio_value}]}
    så chart kan plotte direkte sammen med eksisterende portfolio history.
    """
    if not portfolio_history or not benchmarks_raw:
        return []

    start_date = portfolio_history[0].get("date")
    history_dates = {h.get("date") for h in portfolio_history if h.get("date")}
    benchmarks = (benchmarks_raw or {}).get("benchmarks", {})

    colors = {
        "^OMXC25": "#e3b341",
        "EUNL.DE": "#a371f7",
    }

    out = []
    for ticker, info in benchmarks.items():
        if "error" in (info or {}):
            continue
        hist = (info or {}).get("history", [])
        by_date = {h.get("date"): h.get("close") for h in hist}

        # Find benchmark-close på (eller umiddelbart efter) portfolio start_date
        start_close = None
        if start_date and start_date in by_date:
            start_close = by_date[start_date]
        else:
            sorted_dates = sorted(by_date.keys())
            for d in sorted_dates:
                if start_date is None or d >= start_date:
                    start_close = by_date[d]
                    start_date_used = d
                    break
        if not start_close:
            continue

        # Byg series på portefølje-datoer (skip dage uden benchmark-close)
        series = []
        for hd in sorted(history_dates):
            close = by_date.get(hd)
            if close is None:
                # find sidste tilgængelige tidligere dato
                earlier = [d for d in by_date if d <= hd]
                if earlier:
                    close = by_date[max(earlier)]
            if close:
                value = round(initial_cash * close / start_close, 2)
                series.append({"date": hd, "portfolio_value": value})

        out.append({
            "ticker": ticker,
            "label": (info or {}).get("label", ticker),
            "color": colors.get(ticker, "#8b949e"),
            "history": series,
        })
    return out


def compute_sector_exposure(positions, stocks_list):
    """Sektorfordeling i procent af samlet positionsværdi.

    Positions bruger yf-symbol ("NOVO-B.CO") mens stocks_list bruger saxo-symbol
    ("NOVOb:xcse"). Mapper begge til sector via watchlist.C25.
    """
    sym_to_sector = {}
    try:
        from watchlist import C25
        saxo_to_yf = {s["saxo"]: s["yf"] for s in C25}
    except Exception:
        saxo_to_yf = {}
    for s in stocks_list or []:
        sec = s.get("sector")
        if not sec:
            continue
        saxo = s.get("symbol")
        if saxo:
            sym_to_sector[saxo] = sec
        yf_sym = saxo_to_yf.get(saxo)
        if yf_sym:
            sym_to_sector[yf_sym] = sec

    sectors = {}
    total_val = 0.0
    for p in positions or []:
        shares = float(p.get("shares") or 0)
        price = float(p.get("current_price") or p.get("purchase_price") or 0)
        val = shares * price
        if val <= 0:
            continue
        sec = sym_to_sector.get(p.get("symbol")) or "Ukendt"
        sectors[sec] = sectors.get(sec, 0.0) + val
        total_val += val
    if total_val <= 0:
        return {}
    return {k: round(v / total_val * 100, 1) for k, v in sectors.items()}


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
    analysis_map, analysis_date = load_latest_analysis()

    stocks = []
    for s in C25:
        yf_sym = s["yf"]
        saxo = s["saxo"]
        pdata = prices.get(yf_sym, {})
        kb = km.load(saxo) or {}

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
            "next_earnings_date": pdata.get("next_earnings_date"),
            "overview": kb.get("overview", ""),
            "fin_summary": kb.get("financials", {}).get("summary", ""),
            "news": kb.get("news", [])[:8],
            "technical": technical,
            "analysis": analysis,
            "prices_age": prices_age,
        })

    print(f"[sync_dashboard] Stocks bygget: {len(stocks)} aktier, prices_age={prices_age}")
    return stocks


def sync():
    import github_store

    default = {
        "portfolio": {"initial_cash": INITIAL_CASH, "cash": INITIAL_CASH, "currency": "DKK", "positions": []},
        "history": [],
        "trades": [],
        "stocks": [],
    }
    # Læs frisk fra GitHub, så dashboardet bygges oven på paper_trader's seneste
    # portefølje/handler. Fald tilbage til lokal checkout uden token.
    data, _ = github_store.get_json("data.json", default=None)
    if not data:
        data = load_json_file(DATA_PATH, default)

    # trades + portefølje ejes af paper_trader.py — sync rører dem ikke.
    data.setdefault("trades", [])

    update_history(data)
    data["stocks"] = build_stocks()
    data["latest_decisions"] = load_latest_decisions()

    initial_cash = float(data.get("portfolio", {}).get("initial_cash", INITIAL_CASH))
    data["benchmarks"] = build_benchmark_series(
        data.get("history", []), load_benchmarks(), initial_cash,
    )
    data["sector_exposure_pct"] = compute_sector_exposure(
        data.get("portfolio", {}).get("positions", []), data.get("stocks", []),
    )

    # Skriv lokalt (GitHub Actions' git-step committer det) og push via
    # github_store (retry + 409-håndtering).
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"[sync_dashboard] {len(data.get('trades', []))} handler, {len(data.get('stocks', []))} aktier -> data.json")
    github_store.put_json("data.json", data, f"Dashboard update {ts}")
    print(f"[sync_dashboard] Dashboard: {DASHBOARD_URL}")


if __name__ == "__main__":
    sync()
