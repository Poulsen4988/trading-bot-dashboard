"""
Deep Analyst helper for the US S&P-500 Claude Routine.

Important:
This file does NOT call the Anthropic API. The analysis itself is done by the
Claude Routine agent directly.

Run: python us/analyst.py

The script reads today's screening, prices/latest.json, data.json and the
per-stock knowledge base, then prints a compact analysis package to stdout.
Unlike the Danish bot it does NOT scan the whole universe — it builds ONLY the
deep set:
    union of screening.top (10) + screening.scouts + current portfolio symbols.

Each entry carries a technical snapshot (RSI/SMA/MACD/ATR/Bollinger from
latest.json), the screener score, a `scout` flag, recent news from the KB and
tier='deep'.

After Claude has done the analysis the routine writes
us/analysis/YYYY-MM-DD.json itself (this script does not push).
"""
from __future__ import annotations

import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
from datetime import date
from typing import Any

from watchlist import SP500, YF_TO_NAME  # noqa: F401  (SP500 kept for parity / future use)
import github_store

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
KNOWLEDGE_DIR = os.path.join(SCRIPT_DIR, "knowledge")


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


def _kb_path(yf_sym: str) -> str:
    # <TICKER> = yf symbol with any '.' or '/' replaced by '_'
    safe = yf_sym.replace(".", "_").replace("/", "_")
    return os.path.join(KNOWLEDGE_DIR, f"{safe}.json")


def load_kb(yf_sym: str) -> dict[str, Any]:
    safe = yf_sym.replace(".", "_").replace("/", "_")
    kb, _ = github_store.get_json(f"us/knowledge/{safe}.json", default={})
    return kb or {}


def recent_news(yf_sym: str, limit: int = 5) -> list[dict[str, Any]]:
    """Most recent news for a stock from us/knowledge/<TICKER>.json."""
    kb = load_kb(yf_sym)
    news = (kb.get("news") or [])[:limit]
    return [
        {
            "date": (n.get("date", "") or "")[:10],
            "title": n.get("title"),
            "source": n.get("source"),
            "summary": (n.get("summary") or "")[:240],
            "url": n.get("url", ""),
        }
        for n in news
    ]


def compact_stock_payload(sym, stock, included_because, scout, screener_score=None) -> dict[str, Any]:
    return {
        "symbol": sym,
        "name": stock.get("name") or YF_TO_NAME.get(sym),
        "tier": "deep",
        "included_because": included_because,
        "scout": scout,
        "screener_score": screener_score,
        "currency": "USD",
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
        "technical": stock.get("technical", {}),  # RSI/SMA/MACD/ATR/Bollinger snapshot
        "recent_news": recent_news(sym, limit=5),
    }


def main() -> None:
    date_str = today()
    prices, _ = github_store.get_json("us/prices/latest.json", default={})
    prices = prices or {}
    stocks_data = prices.get("stocks", {})

    screening, _ = github_store.get_json(f"us/screening/{date_str}.json", default={})
    screening = screening or {}
    top_syms = list(screening.get("top") or [])           # top 10
    scout_syms = list(screening.get("scouts") or [])      # >= 2 scouts
    # score lookup from the full scored table
    score_by_sym = {r.get("symbol"): r.get("score") for r in (screening.get("scored") or [])}

    scout_set = set(scout_syms)

    # Current holdings — ALWAYS re-analysed
    data, _ = github_store.get_json("us/data.json", default={})
    data = data or {}
    positions = data.get("portfolio", {}).get("positions", [])
    held_syms = {p.get("symbol") for p in positions if p.get("symbol")}

    # Deep set = top (10) + scouts + holdings. Preserve order: top, then scouts, then holdings.
    deep_order: list[str] = []
    seen: set[str] = set()
    for sym in top_syms + scout_syms + sorted(held_syms):
        if sym and sym not in seen:
            seen.add(sym)
            deep_order.append(sym)

    deep_set = set(deep_order)

    selected = []
    for sym in deep_order:
        if sym not in stocks_data:
            continue
        stock = stocks_data[sym]
        if "error" in stock:
            continue
        in_top = sym in top_syms
        in_scout = sym in scout_set
        in_held = sym in held_syms
        parts = []
        if in_top:
            parts.append("screener top-10")
        if in_scout:
            parts.append("scout")
        if in_held:
            parts.append("current holding")
        because = " + ".join(parts) or "deep set"
        selected.append(compact_stock_payload(
            sym, stock, because, scout=in_scout, screener_score=score_by_sym.get(sym),
        ))

    payload = {
        "date": date_str,
        "prices_date": prices.get("date"),
        "prices_fetched_at": prices.get("fetched_at"),
        "currency": "USD",
        "held_positions": sorted(held_syms),
        "deep_set": sorted(deep_set),
        "tier_counts": {"deep": len(selected), "total": len(selected)},
        "selected_for_analysis": selected,
        "output_file": f"us/analysis/{date_str}.json",
        "instruction": (
            "Deep analysis of the US deep set ONLY (screener top-10 + scouts + current holdings) — "
            "do NOT analyse the full S&P 500 universe.\n"
            "For every stock in selected_for_analysis run a full bull/bear/head-analyst analysis: "
            "verdict (BULL/BEAR/NEUTRAL), confidence (1-10), bull-list, bear-list, summary, key_risk. "
            "Use recent_news and the technical snapshot (RSI/SMA/MACD/ATR/Bollinger) actively. "
            "All monetary context is in USD ($).\n"
            "For each stock include the `scout` flag (True if it came from the screener scouts) and the "
            "`screener_score` in the output.\n"
            "Write output_file (us/analysis/DATE.json) as JSON. Schema:\n"
            "  { date, stocks: { SYM: { tier:'deep', verdict, confidence, bull:[], bear:[], summary, "
            "key_risk, technical:{...}, recent_news:[...], screener_score, scout } } }\n"
            "Only include the deep set in `stocks` — NOT all 503."
        ),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
