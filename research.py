"""
Henter markedsdata til analyse- og paper-trading-beslutninger.

Primær kilde: prices/latest.json, som opdateres af scripts/fetch_prices.py.
Der er ingen Saxo-integration i dette flow.
"""
import json
import os

from watchlist import C25, WATCHLIST

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PRICES_FILE = os.path.join(SCRIPT_DIR, "prices", "latest.json")
DATA_FILE = os.path.join(SCRIPT_DIR, "data.json")


def load_yfinance_data():
    if os.path.exists(PRICES_FILE):
        with open(PRICES_FILE, encoding="utf-8") as f:
            return json.load(f)
    return None


def load_dashboard_portfolio():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("portfolio", {})
    return {}


def get_market_data_from_yfinance(prices):
    stocks = prices.get("stocks", {})
    result = []
    for s in C25:
        data = stocks.get(s["yf"])
        if not data or "error" in data:
            result.append({
                "symbol": s["saxo"],
                "yf_symbol": s["yf"],
                "name": s["name"],
                "uic": s["uic"],
                "tradeable": s["uic"] is not None,
                "error": data.get("error") if data else "missing data",
            })
            continue

        result.append({
            "symbol": s["saxo"],
            "yf_symbol": s["yf"],
            "name": s["name"],
            "uic": s["uic"],
            "tradeable": s["uic"] is not None,
            "price": data.get("price"),
            "pct_1d": data.get("pct_1d"),
            "pct_5d": data.get("pct_5d"),
            "pct_20d": data.get("pct_20d"),
            "pe_forward": data.get("pe_forward"),
            "pe_trailing": data.get("pe_trailing"),
            "div_yield": data.get("div_yield"),
            "volume_ratio": data.get("volume_ratio"),
            "pct_from_52w_high": data.get("pct_from_52w_high"),
            "pct_from_52w_low": data.get("pct_from_52w_low"),
            "revenue_growth": data.get("revenue_growth"),
            "earnings_growth": data.get("earnings_growth"),
            "market_cap": data.get("market_cap"),
            "sector": data.get("sector"),
            "industry": data.get("industry"),
            "source": data.get("source", "yfinance"),
        })
    return result


def normalize_positions(portfolio):
    positions = []
    for p in portfolio.get("positions", []):
        shares = p.get("shares") or p.get("amount") or 0
        avg_price = p.get("avg_price") or p.get("purchase_price") or p.get("open_price")
        current_price = p.get("current_price") or avg_price
        pnl_pct = None
        if avg_price and current_price:
            pnl_pct = round((current_price - avg_price) / avg_price * 100, 2)
        positions.append({
            "symbol": p.get("symbol"),
            "name": p.get("name") or p.get("symbol"),
            "shares": shares,
            "avg_price": avg_price,
            "current_price": current_price,
            "value": shares * current_price if shares and current_price else None,
            "pnl_pct": pnl_pct,
        })
    return positions


def main():
    prices = load_yfinance_data()
    portfolio = load_dashboard_portfolio()
    positions = normalize_positions(portfolio)

    if prices:
        quotes = get_market_data_from_yfinance(prices)
        data_source = "yfinance"
        data_age = prices.get("fetched_at", "ukendt")
    else:
        quotes = []
        data_source = "ingen data"
        data_age = "N/A"

    result = {
        "account": {
            "mode": "paper",
            "currency": portfolio.get("currency", "DKK"),
            "cash": portfolio.get("cash"),
            "initial_cash": portfolio.get("initial_cash", 100000),
        },
        "positions": positions,
        "quotes": quotes,
        "watchlist": [s["name"] for s in C25],
        "tradeable_symbols": [s["name"] for s in WATCHLIST],
        "data_source": data_source,
        "data_age": data_age,
        "total_stocks": len(quotes),
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
