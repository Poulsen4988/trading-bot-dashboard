import yfinance as yf
import json
from datetime import date, datetime
import os

# OMX Copenhagen C25 index constituents (Yahoo Finance tickers)
STOCKS = [
    ("NOVO-B.CO",   "Novo Nordisk B"),
    ("MAERSK-B.CO", "A.P. Moller-Maersk B"),
    ("MAERSK-A.CO", "A.P. Moller-Maersk A"),
    ("DSV.CO",      "DSV"),
    ("ORSTED.CO",   "Oersted"),
    ("CARL-B.CO",   "Carlsberg B"),
    ("PNDORA.CO",   "Pandora"),
    ("TRYG.CO",     "Tryg"),
    ("COLO-B.CO",   "Coloplast B"),
    ("GMAB.CO",     "Genmab"),
    ("GN.CO",       "GN Store Nord"),
    ("DEMANT.CO",   "Demant"),
    ("RBREW.CO",    "Royal Unibrew"),
    ("NDA-DK.CO",   "Nordea Bank"),
    ("FLS.CO",      "FLSmidth"),
    ("VWS.CO",      "Vestas Wind Systems"),
    ("AMBU-B.CO",   "Ambu B"),
    ("NSIS-B.CO",   "Novonesis B"),
    ("ROCK-B.CO",   "Rockwool B"),
    ("BAVA.CO",     "Bavarian Nordic"),
    ("JYSK.CO",     "Jyske Bank"),
    ("ISS.CO",      "ISS"),
    ("SYDB.CO",     "Sydbank"),
    ("NNIT.CO",     "NNIT"),
    ("CHR.CO",      "Chr. Hansen"),
]

results = {}
all_news = {}

for sym, name in STOCKS:
    try:
        t = yf.Ticker(sym)
        h = t.history(period="25d")
        info = {}
        try:
            raw = t.info
            info = {k: raw.get(k) for k in [
                "trailingPE", "forwardPE", "marketCap",
                "fiftyTwoWeekHigh", "fiftyTwoWeekLow",
                "sector", "industry", "shortName",
                "dividendYield", "beta",
                "revenueGrowth", "earningsGrowth",
            ]}
        except Exception:
            pass

        # Fetch recent news headlines
        news_items = []
        try:
            raw_news = t.news or []
            for item in raw_news[:5]:  # top 5 headlines per stock
                news_items.append({
                    "title":     item.get("title", ""),
                    "publisher": item.get("publisher", ""),
                    "link":      item.get("link", ""),
                    "published": item.get("providerPublishTime", 0),
                })
        except Exception:
            pass
        if news_items:
            all_news[sym] = {"name": name, "headlines": news_items}

        if not h.empty:
            closes = h["Close"].tolist()
            vols   = h["Volume"].tolist() if "Volume" in h.columns else []

            price   = round(float(closes[-1]), 2)
            prev    = round(float(closes[-2]), 2) if len(closes) > 1 else price
            pct_1d  = round((price - prev) / prev * 100, 2)
            pct_5d  = round((price - float(closes[-6])) / float(closes[-6]) * 100, 2) if len(closes) >= 6 else None
            pct_20d = round((price - float(closes[0]))  / float(closes[0])  * 100, 2) if len(closes) >= 20 else None

            vol      = int(vols[-1])     if vols else None
            avg_vol  = int(sum(vols) / len(vols)) if vols else None
            vol_ratio = round(vol / avg_vol, 2) if vol and avg_vol and avg_vol > 0 else None

            hi52 = info.get("fiftyTwoWeekHigh")
            lo52 = info.get("fiftyTwoWeekLow")

            results[sym] = {
                "name":              name,
                "price":             price,
                "prev_close":        prev,
                "pct_1d":            pct_1d,
                "pct_5d":            pct_5d,
                "pct_20d":           pct_20d,
                "volume":            vol,
                "avg_volume":        avg_vol,
                "volume_ratio":      vol_ratio,
                "pe_trailing":       info.get("trailingPE"),
                "pe_forward":        info.get("forwardPE"),
                "market_cap":        info.get("marketCap"),
                "52w_high":          hi52,
                "52w_low":           lo52,
                "pct_from_52w_high": round((price - hi52) / hi52 * 100, 2) if hi52 else None,
                "pct_from_52w_low":  round((price - lo52) / lo52 * 100, 2) if lo52 else None,
                "sector":            info.get("sector"),
                "industry":          info.get("industry"),
                "beta":              info.get("beta"),
                "div_yield":         info.get("dividendYield"),
                "revenue_growth":    info.get("revenueGrowth"),
                "earnings_growth":   info.get("earningsGrowth"),
                "source":            "yfinance",
            }
        else:
            results[sym] = {"name": name, "error": "no data returned"}
    except Exception as e:
        results[sym] = {"name": name, "error": str(e)}

ok = sum(1 for v in results.values() if "price" in v)
news_ok = len(all_news)
print(f"Fetched {ok}/{len(STOCKS)} price+fundamentals, {news_ok} with news")

os.makedirs("prices", exist_ok=True)
out = {
    "date":       str(date.today()),
    "fetched_at": datetime.utcnow().isoformat() + "Z",
    "universe":   len(STOCKS),
    "fetched_ok": ok,
    "stocks":     results,
    "news":       all_news,
}
with open("prices/latest.json", "w") as f:
    json.dump(out, f, indent=2)
