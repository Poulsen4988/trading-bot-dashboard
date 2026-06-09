"""
Vedligeholder lang prishistorik for hver C25-aktie via yfinance.
Skriver en fil pr. aktie til prices/history/<yf>.json.

INKREMENTEL som standard: henter kun en kort hale (3 mdr.) og fletter den ind i
den eksisterende fil — kun de nye dage ændres. Fuld genhentning (period="max")
sker når filen mangler, om mandagen (ugentlig), eller når FETCH_FULL_HISTORY er
sat (manuel trigger). Det undgår at gen-downloade og gen-skrive hele historikken
(NOVO tilbage til 1974) hver dag.

Kører ~1x dagligt (efter market close kl 16 UTC) + manuelt via GitHub Actions.

Format pr. fil:
{
  "symbol": "NOVO-B.CO", "name": "Novo Nordisk B",
  "fetched_at": "...", "first_date": "...", "last_date": "...",
  "points": 12345, "history": [{"date": "1974-01-02", "close": 0.05}, ...]
}
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

import yfinance as yf

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPT_DIR)

from watchlist import C25

HISTORY_DIR = os.path.join(SCRIPT_DIR, "prices", "history")
os.makedirs(HISTORY_DIR, exist_ok=True)

now_dt = datetime.now(timezone.utc)
now = now_dt.isoformat()
FULL = os.environ.get("FETCH_FULL_HISTORY", "").lower() in ("1", "true", "yes")
if now_dt.weekday() == 0:  # mandag: ugentlig fuld genhentning som sikkerhedsnet
    FULL = True


def fetch_retry(ticker, period, retries=3, backoff=3):
    last = None
    for attempt in range(retries):
        try:
            df = yf.Ticker(ticker).history(period=period, auto_adjust=True)
            if df is not None and not df.empty:
                return df
            last = "tomt svar"
        except Exception as e:
            last = e
        if attempt < retries - 1:
            time.sleep(backoff * (attempt + 1))
    raise RuntimeError(str(last))


print(f"[fetch_history] Vedligeholder historik for {len(C25)} aktier (full={FULL})...")
failures = 0

for s in C25:
    sym = s["yf"]
    path = os.path.join(HISTORY_DIR, f"{sym}.json")

    existing = None
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = None

    full_this = FULL or not existing or not existing.get("history")

    try:
        df = fetch_retry(sym, "max" if full_this else "3mo")
    except Exception as e:
        failures += 1
        # Behold den eksisterende fil ved fejl — overskriv ikke god historik.
        print(f"[fetch_history]   FEJL {s['name']}: {e}", file=sys.stderr)
        time.sleep(1)
        continue

    closes = df["Close"].dropna()
    new_points = [
        {"date": idx.date().isoformat(), "close": round(float(c), 4)}
        for idx, c in closes.items()
    ]
    if not new_points:
        failures += 1
        print(f"[fetch_history]   {s['name']}: INGEN DATA — beholder eksisterende", file=sys.stderr)
        continue

    if full_this or not existing:
        history = new_points
        mode = "fuld"
    else:
        by_date = {p["date"]: p for p in existing.get("history", [])}
        added = sum(1 for p in new_points if p["date"] not in by_date)
        for p in new_points:
            by_date[p["date"]] = p
        history = [by_date[d] for d in sorted(by_date)]
        mode = f"inkrementel (+{added})"

    payload = {
        "symbol": sym,
        "name": s["name"],
        "fetched_at": now,
        "first_date": history[0]["date"],
        "last_date": history[-1]["date"],
        "points": len(history),
        "history": history,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    print(f"[fetch_history]   {s['name']}: {len(history)} dage ({mode})")
    time.sleep(0.5)  # skån yfinance for rate-limit

if failures == len(C25):
    print("[fetch_history] FEJL: alle hentninger fejlede.", file=sys.stderr)
    sys.exit(1)

print(f"[fetch_history] Færdig — {failures} fejl af {len(C25)} ({HISTORY_DIR})")
