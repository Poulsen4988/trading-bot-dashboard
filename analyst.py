"""
Deep Analyst helper til Claude Routine.

Vigtigt:
Denne fil kalder IKKE Anthropic API. Selve analysen skal laves af Claude
Routine-agenten direkte.

Kør: python analyst.py

Scriptet læser dagens screening, prices/latest.json, data.json og videnbasen
og printer en kompakt analysepakke til stdout. Pakken indeholder:
  - screenerens top-picks
  - ALLE nuværende beholdninger (altid re-analyseret, også uden for top-picks)
  - seneste nyheder per aktie fra videnbasen (yfinance + Nasdaq Copenhagen)

Efter Claude har lavet analysen, skal routinen selv skrive
analysis/YYYY-MM-DD.json.
"""
from __future__ import annotations

import json
import os
from datetime import date
from typing import Any

import knowledge_manager as km
from watchlist import C25

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
YF_TO_SAXO = {s["yf"]: s["saxo"] for s in C25}
YF_TO_NAME = {s["yf"]: s["name"] for s in C25}


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


def recent_news(yf_sym: str, limit: int = 6) -> list[dict[str, Any]]:
    """Seneste nyheder for en aktie fra videnbasen."""
    saxo = YF_TO_SAXO.get(yf_sym)
    if not saxo:
        return []
    kb = km.load(saxo) or {}
    news = kb.get("news", [])[:limit]
    return [
        {
            "date": n.get("date", "")[:10],
            "title": n.get("title"),
            "source": n.get("source"),
            "summary": (n.get("summary") or "")[:240],
            "url": n.get("url", ""),
        }
        for n in news
    ]


def compact_stock_payload(sym, stock, rationale, included_because) -> dict[str, Any]:
    return {
        "symbol": sym,
        "name": stock.get("name") or YF_TO_NAME.get(sym),
        "included_because": included_because,
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
        "screening_rationale": rationale,
        "recent_news": recent_news(sym),
    }


def main() -> None:
    date_str = today()
    prices = load_json("prices/latest.json", default={})
    stocks_data = prices.get("stocks", {})

    # Screenerens top-picks
    screening = load_json(f"screening/{date_str}.json", default={}) or {}
    screening_rows = (screening.get("selected") or [])[:5]
    screening_by_sym = {r.get("symbol"): r for r in screening_rows}

    # Nuværende beholdninger — skal ALTID analyseres
    data = load_json("data.json", default={}) or {}
    positions = data.get("portfolio", {}).get("positions", [])
    held_syms = {p.get("symbol") for p in positions if p.get("symbol")}

    # Union: top-picks + beholdninger
    order = [r.get("symbol") for r in screening_rows]
    for h in held_syms:
        if h not in order:
            order.append(h)

    selected = []
    for sym in order:
        if not sym or sym not in stocks_data:
            continue
        stock = stocks_data[sym]
        if "error" in stock:
            continue
        in_screen = sym in screening_by_sym
        in_held = sym in held_syms
        if in_screen and in_held:
            because = "screener-pick + nuværende beholdning"
        elif in_held:
            because = "nuværende beholdning"
        else:
            because = "screener-pick"
        row = screening_by_sym.get(sym, {})
        rationale = (
            row.get("rationale")
            or row.get("screening_rationale")
            or ("Nuværende beholdning — altid re-analyseret" if in_held else "Udvalgt af screener")
        )
        selected.append(compact_stock_payload(sym, stock, rationale, because))

    payload = {
        "date": date_str,
        "prices_date": prices.get("date"),
        "prices_fetched_at": prices.get("fetched_at"),
        "held_positions": sorted(held_syms),
        "selected_for_analysis": selected,
        "output_file": f"analysis/{date_str}.json",
        "instruction": (
            "Lav bull/bear/head-analyst analyse af ALLE aktier i selected_for_analysis "
            "(både screener-picks og nuværende beholdninger). Brug recent_news og "
            "technical aktivt. Skriv output_file som JSON."
        ),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
