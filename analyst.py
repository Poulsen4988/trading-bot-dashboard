"""
Deep Analyst helper til Claude Routine.

Vigtigt:
Denne fil kalder IKKE Anthropic API. Selve analysen skal laves af Claude
Routine-agenten direkte.

Kør: python analyst.py

Scriptet læser dagens screening og prices/latest.json og printer en kompakt
analysepakke til stdout, så Claude-routinen kan bruge den som input. Efter
Claude har lavet analysen, skal routinen selv skrive analysis/YYYY-MM-DD.json,
commit og push.
"""
from __future__ import annotations

import json
import os
from datetime import date
from typing import Any

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def today() -> str:
    return date.today().isoformat()


def load_json(path: str, default: Any = None) -> Any:
    try:
        with open(os.path.join(SCRIPT_DIR, path), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError:
        return default


def load_screening(date_str: str) -> list[dict[str, Any]]:
    screening = load_json(f"screening/{date_str}.json", default=None)
    if not screening:
        return []
    selected = screening.get("selected") or []
    return selected[:5]


def compact_stock_payload(sym: str, stock: dict[str, Any], screening_rationale: str) -> dict[str, Any]:
    return {
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


def main() -> None:
    date_str = today()
    prices = load_json("prices/latest.json", default={})
    stocks_data = prices.get("stocks", {})
    screening_rows = load_screening(date_str)

    selected = []
    for row in screening_rows:
        sym = row.get("symbol")
        if not sym or sym not in stocks_data:
            continue
        stock = stocks_data[sym]
        if "error" in stock:
            continue
        selected.append(compact_stock_payload(
            sym,
            stock,
            row.get("rationale") or row.get("screening_rationale") or "Udvalgt af screener",
        ))

    payload = {
        "date": date_str,
        "prices_date": prices.get("date"),
        "prices_fetched_at": prices.get("fetched_at"),
        "selected_for_analysis": selected,
        "output_file": f"analysis/{date_str}.json",
        "instruction": "Claude-routinen skal lave bull/bear/head analyst analyse og skrive output_file som JSON.",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
