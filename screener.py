"""
Screener Agent.

Kør: python screener.py
- Opdaterer prices/latest.json lokalt med tekniske indikatorer.
- Vælger 3-5 mest interessante C25-aktier.
- Gemmer screening/YYYY-MM-DD.json via GitHub token hvis tilgængelig,
  ellers lokalt.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, datetime, timezone

import github_store

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PRICES_PATH = os.path.join(SCRIPT_DIR, "prices", "latest.json")


def run_price_fetch():
    subprocess.check_call([sys.executable, os.path.join(SCRIPT_DIR, "scripts", "fetch_prices.py")], cwd=SCRIPT_DIR)


def load_prices():
    with open(PRICES_PATH, encoding="utf-8") as f:
        return json.load(f)


def score_stock(sym: str, s: dict) -> tuple[float, list[str]]:
    if "error" in s:
        return -999, [f"Dataproblem: {s['error']}"]

    score = 0.0
    reasons: list[str] = []
    tech = s.get("technical", {}) or {}

    pct_5d = s.get("pct_5d")
    pct_20d = s.get("pct_20d")
    volume_ratio = s.get("volume_ratio")
    pe_forward = s.get("pe_forward")
    earnings_growth = s.get("earnings_growth")
    revenue_growth = s.get("revenue_growth")
    pct_from_low = s.get("pct_from_52w_low")
    pct_from_high = s.get("pct_from_52w_high")
    rsi = tech.get("rsi")

    if volume_ratio and volume_ratio >= 1.5:
        score += 2.0
        reasons.append(f"Høj volumen ({volume_ratio}x gennemsnit) kan signalere institutionel interesse")
    elif volume_ratio and volume_ratio >= 1.0:
        score += 1.0
        reasons.append(f"Volumen over gennemsnit ({volume_ratio}x)")

    if pct_5d is not None:
        if pct_5d <= -6:
            score += 1.6
            reasons.append(f"Kraftig 5-dages svaghed ({pct_5d}%) giver mulig reversal-kandidat")
        elif pct_5d >= 4:
            score += 1.3
            reasons.append(f"Stærkt 5-dages momentum ({pct_5d}%)")

    if pct_20d is not None:
        if pct_20d <= -10:
            score += 1.1
            reasons.append(f"20-dages pres ({pct_20d}%) kan give value/reversal-case")
        elif pct_20d >= 10:
            score += 1.0
            reasons.append(f"20-dages momentum ({pct_20d}%)")

    if rsi is not None:
        if rsi < 35:
            score += 1.2
            reasons.append(f"RSI {rsi} nær/under oversolgt niveau")
        elif rsi > 65:
            score += 0.8
            reasons.append(f"RSI {rsi} viser stærk momentum men kræver risikotjek")

    if tech.get("macd_cross") == "bullish":
        score += 0.9
        reasons.append("MACD-histogram er positivt")
    elif tech.get("macd_cross") == "bearish":
        score += 0.4
        reasons.append("MACD er bearish — interessant som risikocase/short avoid")

    if tech.get("trend") == "above_200ma":
        score += 0.7
        reasons.append("Kurs over 200-dages glidende gennemsnit")
    elif tech.get("trend") == "below_200ma":
        score += 0.5
        reasons.append("Kurs under 200-dages snit — kræver dyb risikoanalyse")

    if pe_forward and pe_forward > 0 and pe_forward < 15:
        score += 1.0
        reasons.append(f"Lav forward P/E ({pe_forward}) relativt til markedet")
    elif pe_forward and pe_forward > 30:
        score += 0.5
        reasons.append(f"Høj forward P/E ({pe_forward}) gør valuation-risiko vigtig")

    if earnings_growth and earnings_growth > 0.15:
        score += 1.0
        reasons.append(f"Stærk earnings growth ({round(earnings_growth*100,1)}%)")
    elif earnings_growth and earnings_growth < -0.15:
        score += 0.6
        reasons.append(f"Negativ earnings growth ({round(earnings_growth*100,1)}%) kræver bear-case")

    if revenue_growth and abs(revenue_growth) >= 0.08:
        score += 0.5
        reasons.append(f"Markant revenue growth ({round(revenue_growth*100,1)}%)")

    if pct_from_low is not None and pct_from_low < 8:
        score += 0.8
        reasons.append(f"Handler tæt på 52-ugers bund ({pct_from_low}% over low)")
    if pct_from_high is not None and pct_from_high < -40:
        score += 0.8
        reasons.append(f"Stor afstand til 52-ugers top ({pct_from_high}%)")

    return score, reasons[:6]


def main():
    run_price_fetch()
    prices = load_prices()
    rows = []
    for sym, s in prices.get("stocks", {}).items():
        score, reasons = score_stock(sym, s)
        if score <= -100:
            continue
        rows.append({
            "symbol": sym,
            "name": s.get("name", sym),
            "score": round(score, 2),
            "price": s.get("price"),
            "pct_1d": s.get("pct_1d"),
            "pct_5d": s.get("pct_5d"),
            "pct_20d": s.get("pct_20d"),
            "pe_forward": s.get("pe_forward"),
            "volume_ratio": s.get("volume_ratio"),
            "technical": s.get("technical", {}),
            "rationale": "; ".join(reasons) if reasons else "Ingen stærke signaler, men valgt til diversificeret gennemgang",
        })

    rows.sort(key=lambda x: x["score"], reverse=True)
    selected = rows[:5]
    payload = {
        "date": date.today().isoformat(),
        "screened_at": datetime.now(timezone.utc).isoformat(),
        "source_prices_date": prices.get("date"),
        "selected": selected,
        "universe_ranked": rows,
    }
    path = f"screening/{payload['date']}.json"
    github_store.put_json(path, payload, f"Screening {payload['date']}")

    print("=== SELECTED FOR DEEP ANALYSIS ===")
    for row in selected:
        print(f"{row['symbol']}: score={row['score']} price={row['price']} — {row['rationale']}")


if __name__ == "__main__":
    main()
