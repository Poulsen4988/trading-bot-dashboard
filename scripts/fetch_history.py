"""
Henter max-længde prishistorik for hver C25-aktie via yfinance.
Skriver en fil pr. aktie til prices/history/<yf>.json.

Kører ~1x om dagen (typisk efter market close kl 16 UTC) via GitHub Actions.

Format pr. fil:
{
  "symbol": "NOVO-B.CO",
  "name": "Novo Nordisk B",
  "fetched_at": "2026-05-23T17:00:00Z",
  "first_date": "1974-...",
  "last_date": "2026-05-23",
  "points": 12345,
  "history": [
    {"date": "1974-01-02", "close": 0.05},
    ...
  ]
}
"""
import json
import os
import sys
from datetime import datetime, timezone

import yfinance as yf

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPT_DIR)

from watchlist import C25

HISTORY_DIR = os.path.join(SCRIPT_DIR, "prices", "history")
os.makedirs(HISTORY_DIR, exist_ok=True)

print(f"[fetch_history] Henter max-historik for {len(C25)} aktier...")
now = datetime.now(timezone.utc).isoformat()

for s in C25:
    sym = s["yf"]
    try:
        t = yf.Ticker(sym)
        df = t.history(period="max", auto_adjust=True)
        closes = df["Close"].dropna()
        if closes.empty:
            print(f"[fetch_history]   {s['name']}: INGEN DATA")
            continue

        history = [
            {"date": idx.date().isoformat(), "close": round(float(c), 4)}
            for idx, c in closes.items()
        ]
        payload = {
            "symbol": sym,
            "name": s["name"],
            "fetched_at": now,
            "first_date": history[0]["date"],
            "last_date": history[-1]["date"],
            "points": len(history),
            "history": history,
        }
        out = os.path.join(HISTORY_DIR, f"{sym}.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        print(f"[fetch_history]   {s['name']}: {len(history)} dage ({history[0]['date']} → {history[-1]['date']})")
    except Exception as e:
        print(f"[fetch_history]   FEJL {s['name']}: {e}")

print(f"[fetch_history] Færdig — historik gemt i {HISTORY_DIR}")
