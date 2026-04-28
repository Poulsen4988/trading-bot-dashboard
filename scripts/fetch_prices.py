import yfinance as yf, json
from datetime import date, datetime

stocks = [
    ("NOVO-B.CO",   "Novo Nordisk B"),
    ("MAERSK-B.CO", "Maersk B"),
    ("DSV.CO",      "DSV"),
]
results = {}
for sym, name in stocks:
    try:
        t = yf.Ticker(sym)
        h = t.history(period="5d")
        if not h.empty:
            price = round(float(h["Close"].iloc[-1]), 2)
            prev  = round(float(h["Close"].iloc[-2]), 2) if len(h) > 1 else price
            pct   = round((price - prev) / prev * 100, 2)
            results[sym] = {"name": name, "price": price, "prev_close": prev, "pct_change": pct, "source": "yfinance"}
            print(f"{sym}: {price} DKK ({pct:+.2f}%)")
        else:
            results[sym] = {"name": name, "error": "no data"}
    except Exception as e:
        results[sym] = {"name": name, "error": str(e)}
        print(f"{sym}: ERROR {e}")

import os
os.makedirs("prices", exist_ok=True)
out = {"date": str(date.today()), "fetched_at": datetime.utcnow().isoformat() + "Z", "stocks": results}
with open("prices/latest.json", "w") as f:
    json.dump(out, f, indent=2)
print("Saved prices/latest.json")
print(json.dumps(out, indent=2))
