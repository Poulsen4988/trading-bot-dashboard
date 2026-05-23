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


def compact_stock_payload(sym, stock, rationale, included_because, tier, screener_score=None) -> dict[str, Any]:
    news_limit = 6 if tier == "deep" else 2
    payload = {
        "symbol": sym,
        "name": stock.get("name") or YF_TO_NAME.get(sym),
        "tier": tier,
        "included_because": included_because,
        "screener_score": screener_score,
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
        "recent_news": recent_news(sym, limit=news_limit),
    }
    return payload


def main() -> None:
    date_str = today()
    prices = load_json("prices/latest.json", default={})
    stocks_data = prices.get("stocks", {})

    # Screenerens top-picks
    screening = load_json(f"screening/{date_str}.json", default={}) or {}
    screening_rows = (screening.get("selected") or [])[:5]
    screening_by_sym = {r.get("symbol"): r for r in screening_rows}

    # Hele scoringstabellen (alle 25) til scan-tier prioritering
    all_scores = {row.get("symbol"): row.get("score") for row in (screening.get("all_scores") or [])}

    # Nuværende beholdninger — skal ALTID analyseres (deep tier)
    data = load_json("data.json", default={}) or {}
    positions = data.get("portfolio", {}).get("positions", [])
    held_syms = {p.get("symbol") for p in positions if p.get("symbol")}

    # Deep tier: top-5 screener-picks + alle beholdninger
    deep_syms = set(screening_by_sym.keys()) | held_syms

    # Scan tier: resten af C25-universet (alt i prices/latest.json som ikke er deep)
    universe = [s["yf"] for s in C25]
    scan_syms = [s for s in universe if s not in deep_syms and s in stocks_data and "error" not in stocks_data.get(s, {})]
    scan_syms.sort(key=lambda s: all_scores.get(s, 0), reverse=True)

    # Deep først (top-5 rækkefølge → derefter holdings ikke i top-5)
    deep_order = [r.get("symbol") for r in screening_rows if r.get("symbol") in deep_syms]
    for h in sorted(held_syms):
        if h not in deep_order:
            deep_order.append(h)

    selected = []

    for sym in deep_order:
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
        selected.append(compact_stock_payload(
            sym, stock, rationale, because, tier="deep", screener_score=all_scores.get(sym),
        ))

    for sym in scan_syms:
        stock = stocks_data[sym]
        rationale = f"Scan-tier — screener score {all_scores.get(sym)}"
        selected.append(compact_stock_payload(
            sym, stock, rationale, "scan-tier (resten af C25)", tier="scan", screener_score=all_scores.get(sym),
        ))

    deep_count = sum(1 for s in selected if s["tier"] == "deep")
    scan_count = sum(1 for s in selected if s["tier"] == "scan")

    payload = {
        "date": date_str,
        "prices_date": prices.get("date"),
        "prices_fetched_at": prices.get("fetched_at"),
        "held_positions": sorted(held_syms),
        "tier_counts": {"deep": deep_count, "scan": scan_count, "total": deep_count + scan_count},
        "selected_for_analysis": selected,
        "output_file": f"analysis/{date_str}.json",
        "instruction": (
            "Tiered analyse af ALLE C25-aktier:\n"
            "- tier=deep (top-5 screener-picks + beholdninger): fuld bull/bear/head-analyst analyse "
            "med bull/bear-lister, summary, key_risk. Brug recent_news og technical aktivt.\n"
            "- tier=scan (resten): kort vurdering pr. aktie — verdict (BULL/BEAR/NEUTRAL), "
            "confidence (1-10), summary (1 sætning), bull (max 1 punkt), bear (max 1 punkt), "
            "key_risk (1 sætning). Spring news-research over, brug kun price-action + technical + screener_score.\n"
            "Skriv output_file (analysis/DATO.json) som JSON med alle 25 aktier i samme format."
        ),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
