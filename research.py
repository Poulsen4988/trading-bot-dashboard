"""
Henter markedsdata til handelsbeslutninger.
Primær kilde: prices/latest.json (yfinance, opdateret af GitHub Actions kl. 06:00).
Fallback: Saxo Bank live API.
"""
import json
import os
import sys

from watchlist import C25, WATCHLIST

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PRICES_FILE = os.path.join(SCRIPT_DIR, "prices", "latest.json")


def load_yfinance_data():
    if os.path.exists(PRICES_FILE):
        with open(PRICES_FILE, encoding="utf-8") as f:
            return json.load(f)
    return None


def get_market_data_from_yfinance(prices):
    stocks = prices.get("stocks", {})
    result = []
    for s in C25:
        data = stocks.get(s["yf"])
        if not data or "error" in data:
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
            "pe_forward": data.get("pe_forward"),
            "pe_trailing": data.get("pe_trailing"),
            "div_yield": data.get("div_yield"),
            "volume_ratio": data.get("volume_ratio"),
            "pct_from_52w_high": data.get("pct_from_52w_high"),
            "pct_from_52w_low": data.get("pct_from_52w_low"),
            "revenue_growth": data.get("revenue_growth"),
            "earnings_growth": data.get("earnings_growth"),
        })
    return result


def get_account_info():
    try:
        import saxo_client as saxo
        data = saxo.get("/port/v1/accounts/me")
        accounts = data.get("Data", [])
        if not accounts:
            return {}
        acc = accounts[0]
        return {
            "account_key": acc.get("AccountKey"),
            "currency": acc.get("Currency"),
            "client_key": acc.get("ClientKey"),
        }
    except Exception as e:
        return {"error": str(e)}


def get_positions(client_key):
    try:
        import saxo_client as saxo
        data = saxo.get("/port/v1/positions/me", params={"ClientKey": client_key})
        positions = []
        for p in data.get("Data", []):
            pd = p.get("PositionBase", {})
            pv = p.get("PositionView", {})
            positions.append({
                "symbol": pd.get("Symbol"),
                "amount": pd.get("Amount"),
                "open_price": pd.get("OpenPrice"),
                "current_price": pv.get("CurrentPrice"),
                "pnl": pv.get("ProfitLossOnTrade"),
                "pnl_pct": (
                    round((pv.get("CurrentPrice", 0) - pd.get("OpenPrice", 0))
                          / pd.get("OpenPrice", 1) * 100, 2)
                    if pd.get("OpenPrice") else None
                ),
            })
        return positions
    except Exception as e:
        return [{"error": str(e)}]


def main():
    prices = load_yfinance_data()
    account = get_account_info()
    client_key = account.get("client_key")
    positions = get_positions(client_key) if client_key else []

    if prices:
        quotes = get_market_data_from_yfinance(prices)
        data_source = "yfinance"
        data_age = prices.get("fetched_at", "ukendt")
    else:
        quotes = []
        data_source = "ingen data"
        data_age = "N/A"

    result = {
        "account": account,
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
