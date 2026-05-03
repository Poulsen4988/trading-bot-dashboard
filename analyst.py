"""
Deep Analyst Agent.

Kør: python analyst.py

Læser dagens screening og prices/latest.json, laver bull/bear/head analyst
for 3-5 udvalgte aktier og gemmer analysis/YYYY-MM-DD.json.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timezone
from typing import Any

import anthropic
import github_store

DEFAULT_FALLBACK = ["NOVO-B.CO", "DSV.CO", "VWS.CO"]
MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")


def today():
    return date.today().isoformat()


def ask_claude(prompt: str) -> str:
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


def parse_json_object(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise


def load_screening(date_str: str):
    screening, _ = github_store.get_json(f"screening/{date_str}.json", default=None)
    if not screening:
        return [{"symbol": s, "rationale": "Fallback: ingen screening-fil fundet"} for s in DEFAULT_FALLBACK]
    selected = screening.get("selected") or []
    return selected[:5] or [{"symbol": s, "rationale": "Fallback: tom screening-fil"} for s in DEFAULT_FALLBACK]


def compact_stock_payload(sym: str, stock: dict[str, Any], screening_rationale: str) -> str:
    fields = {
        "symbol": sym,
        "name": stock.get("name"),
        "price": stock.get("price"),
        "pct_1d": stock.get("pct_1d"),
        "pct_5d": stock.get("pct_5d"),
        "pct_20d": stock.get("pct_20d"),
        "volume_ratio": stock.get("volume_ratio"),
        "pe_trailing": stock.get("pe_trailing"),
        "pe_forward": stock.get("pe_forward"),
        "div_yield": stock.get("div_yield"),
        "revenue_growth": stock.get("revenue_growth"),
        "earnings_growth": stock.get("earnings_growth"),
        "pct_from_52w_high": stock.get("pct_from_52w_high"),
        "pct_from_52w_low": stock.get("pct_from_52w_low"),
        "sector": stock.get("sector"),
        "industry": stock.get("industry"),
        "technical": stock.get("technical", {}),
        "screening_rationale": screening_rationale,
    }
    return json.dumps(fields, ensure_ascii=False, indent=2)


def analyze_stock(sym: str, stock: dict[str, Any], screening_rationale: str) -> dict[str, Any]:
    prompt = f"""Du er DEEP ANALYST AGENT for en virtuel paper-trading bot på OMX Copenhagen/C25.

Analyser denne aktie med tre roller: BULL ANALYST, BEAR ANALYST og HEAD ANALYST.
Brug kun de data du får her, og vær ærlig om usikkerhed.

AKTIEDATA:
{compact_stock_payload(sym, stock, screening_rationale)}

BULL ANALYST:
- Byg stærkeste bull case med valuation, vækst, moat, momentum, volumen, katalysatorer og makro.
- Skriv 3-4 konkrete punkter.
- Angiv realistisk 12-måneders upside i procent.

BEAR ANALYST:
- Byg stærkeste bear case med valuation-risiko, vækst/margins, konkurrence, price action, nyheder og makro.
- Skriv 3-4 konkrete punkter.
- Angiv realistisk 12-måneders downside i procent som negativt tal.

HEAD ANALYST:
- Vægt bull vs bear efter styrke og sandsynlighed.
- Vurder momentum og positionering.
- Verdict skal være BULL, BEAR eller NEUTRAL.
- Confidence 0-100. Hvis confidence er under 55, skal verdict normalt være NEUTRAL.
- Skriv en 2-sætnings syntese og én vigtig key risk.

Svar KUN med JSON i dette format:
{{
  "bull": ["point1", "point2", "point3"],
  "bull_upside_pct": 15,
  "bear": ["point1", "point2", "point3"],
  "bear_downside_pct": -20,
  "verdict": "BULL",
  "confidence": 72,
  "summary": "To sætninger med head analyst verdict.",
  "key_risk": "Vigtigste risiko for at vurderingen er forkert."
}}"""
    raw = ask_claude(prompt)
    parsed = parse_json_object(raw)
    confidence = int(parsed.get("confidence") or 0)
    verdict = str(parsed.get("verdict", "NEUTRAL")).upper()
    if confidence < 55 and verdict != "NEUTRAL":
        verdict = "NEUTRAL"
        parsed["summary"] = (parsed.get("summary", "") + " Confidence er under 55, så verdict normaliseres til NEUTRAL.").strip()
    parsed["verdict"] = verdict if verdict in {"BULL", "BEAR", "NEUTRAL"} else "NEUTRAL"
    parsed["confidence"] = max(0, min(100, confidence))
    return parsed


def main():
    date_str = today()
    screening_rows = load_screening(date_str)
    prices, _ = github_store.get_json("prices/latest.json", default=None)
    if not prices:
        local_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prices", "latest.json")
        with open(local_path, encoding="utf-8") as f:
            prices = json.load(f)

    stocks_data = prices.get("stocks", {})
    result_stocks = {}

    for row in screening_rows:
        sym = row.get("symbol")
        if not sym or sym not in stocks_data:
            continue
        stock = stocks_data[sym]
        if "error" in stock:
            continue
        screening_rationale = row.get("rationale") or row.get("screening_rationale") or "Udvalgt af screener"
        analysis = analyze_stock(sym, stock, screening_rationale)
        result_stocks[sym] = {
            "name": stock.get("name", sym),
            "price": stock.get("price"),
            "pct_1d": stock.get("pct_1d"),
            "pe_forward": stock.get("pe_forward"),
            "volume_ratio": stock.get("volume_ratio"),
            "screening_rationale": screening_rationale,
            **analysis,
        }

    payload = {
        "date": date_str,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "stocks": result_stocks,
    }
    github_store.put_json(f"analysis/{date_str}.json", payload, f"Deep analysis {date_str}")

    print("=== FINAL VERDICTS ===")
    for sym, s in result_stocks.items():
        print(f"{sym}: {s['verdict']} confidence={s['confidence']} price={s['price']} — {s['summary']}")


if __name__ == "__main__":
    main()
