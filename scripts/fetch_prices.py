"""
Henter dagens priser for alle C25-aktier via yfinance.
Gemmer til prices/latest.json.
Køres af GitHub Actions før bot-kørslerne.
"""
import json
import os
import sys
from datetime import datetime, timezone

import yfinance as yf

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPT_DIR)

from watchlist import C25

os.makedirs(os.path.join(SCRIPT_DIR, "prices"), exist_ok=True)

tickers = [s["yf"] for s in C25]
print(f"[fetch_prices] Henter {len(tickers)} aktier...")

data = yf.download(tickers, period="30d", interval="1d", auto_adjust=True, progress=False)

stocks = {}
for s in C25:
    sym = s["yf"]
    try:
        t = yf.Ticker(sym)
        info = t.info
        close = data["Close"][sym].dropna()
        price = float(close.iloc[-1]) if len(close) >= 1 else None
        pct_1d = float((close.iloc[-1] / close.iloc[-2] - 1) * 100) if len(close) >= 2 else None
        pct_5d = float((close.iloc[-1] / close.iloc[-6] - 1) * 100) if len(close) >= 6 else None
        pct_20d = float((close.iloc[-1] / close.iloc[-21] - 1) * 100) if len(close) >= 21 else None
        hi52 = info.get("fiftyTwoWeekHigh")
        lo52 = info.get("fiftyTwoWeekLow")
        avg_vol = info.get("averageVolume")
        vol = info.get("regularMarketVolume")

        # Udbytteafkast — eneste sandhed. yfinance returnerer dividendYield
        # som procent-tal direkte (0.44 = 0.44%, 5.31 = 5.31%).
        # >30 antages at være et bogus dividendbeløb i valuta.
        raw_dy = info.get("dividendYield")
        if raw_dy is None or raw_dy < 0 or raw_dy > 30:
            div_yield = None
        else:
            div_yield = round(raw_dy, 2)

        stocks[sym] = {
            "price": round(price, 2) if price is not None else None,
            "pct_1d": round(pct_1d, 2) if pct_1d is not None else None,
            "pct_5d": round(pct_5d, 2) if pct_5d is not None else None,
            "pct_20d": round(pct_20d, 2) if pct_20d is not None else None,
            "pe_forward": info.get("forwardPE"),
            "pe_trailing": info.get("trailingPE"),
            "div_yield": div_yield,
            "volume_ratio": round(vol / avg_vol, 2) if vol and avg_vol else None,
            "52w_high": hi52,
            "52w_low": lo52,
            "pct_from_52w_high": round((price / hi52 - 1) * 100, 2) if price and hi52 else None,
            "pct_from_52w_low": round((price / lo52 - 1) * 100, 2) if price and lo52 else None,
            "revenue_growth": info.get("revenueGrowth"),
            "earnings_growth": info.get("earningsGrowth"),
            "market_cap": info.get("marketCap"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
        }
        print(f"[fetch_prices]   {s['name']}: {price}")
    except Exception as e:
        stocks[sym] = {"error": str(e)}
        print(f"[fetch_prices]   FEJL {s['name']}: {e}")

now = datetime.now(timezone.utc)
result = {
    "date": now.date().isoformat(),
    "fetched_at": now.isoformat(),
    "stocks": stocks,
}
out = os.path.join(SCRIPT_DIR, "prices", "latest.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

ok = sum(1 for v in stocks.values() if "error" not in v and v.get("price"))
print(f"[fetch_prices] Faerdig: {ok}/{len(tickers)} aktier hentet -> {out}")
