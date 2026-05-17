"""
Decision Prep — printer portefølje + analyse til stdout.

Kør: python decision_prep.py

Henter analysis/YYYY-MM-DD.json, data.json og prices/latest.json fra GitHub,
samt seneste nyheder og tekniske indikatorer per aktie. Printer en kompakt
beslutningspakke til stdout så handels-rutinen kan tage kvalificerede
BUY/SELL/HOLD beslutninger.
Output skrives til decisions/YYYY-MM-DD.json af rutinen selv.
"""
from __future__ import annotations

import json
from datetime import date
from math import floor

import github_store
from watchlist import C25

YF_TO_SAXO = {s["yf"]: s["saxo"] for s in C25}
_news_cache: dict[str, list] = {}

TECH_KEYS = (
    "rsi", "stoch", "bb_position", "macd_line", "atr",
    "sma50_vs_price", "sma200_vs_price", "momentum_5d",
    "momentum_20d", "momentum_divergence",
)


def today() -> str:
    return date.today().isoformat()


def pnl_pct(purchase_price, current_price):
    if not purchase_price or not current_price:
        return None
    return (float(current_price) / float(purchase_price) - 1) * 100


def knowledge_news(yf_sym, limit=6):
    """Seneste nyheder for en aktie fra videnbasen (yfinance + Nasdaq)."""
    saxo = YF_TO_SAXO.get(yf_sym)
    if not saxo:
        return []
    if saxo in _news_cache:
        return _news_cache[saxo]
    safe = saxo.replace(":", "_").replace("/", "_").replace(" ", "_")
    kb, _ = github_store.get_json(f"knowledge/{safe}.json", default={})
    news = (kb or {}).get("news", [])[:limit]
    out = [
        {
            "date": (n.get("date") or "")[:10],
            "title": n.get("title"),
            "source": n.get("source"),
            "summary": (n.get("summary") or "")[:200],
            "url": n.get("url", ""),
        }
        for n in news
    ]
    _news_cache[saxo] = out
    return out


def compact_technical(prices, sym):
    t = (prices.get(sym, {}) or {}).get("technical") or {}
    return {k: t.get(k) for k in TECH_KEYS} if t else {}


def main() -> None:
    date_str = today()

    # --- Hent data ---
    analysis, _ = github_store.get_json(f"analysis/{date_str}.json", default=None)
    data, _ = github_store.get_json("data.json", default={"portfolio": {"cash": 100000, "positions": []}, "trades": [], "history": []})
    prices_raw, _ = github_store.get_json("prices/latest.json", default={})
    prices = prices_raw.get("stocks", {})

    if not analysis:
        raise SystemExit(f"FEJL: Ingen analysis/{date_str}.json — kør analyse-rutinen først.")

    portfolio = data.get("portfolio", {})
    cash = float(portfolio.get("cash", 100000))
    positions = portfolio.get("positions", [])
    stocks = analysis.get("stocks", {})

    # Beregn total porteføljeværdi
    positions_value = sum(
        float(p.get("shares", 0)) * float(
            prices.get(p.get("symbol"), {}).get("price")
            or p.get("current_price")
            or p.get("purchase_price")
            or 0
        )
        for p in positions
    )
    total_value = cash + positions_value
    buy_budget = min(total_value * 0.20, max(0, cash - 2500))

    # --- Output ---
    out = {}

    out["meta"] = {
        "date": date_str,
        "prices_fetched_at": prices_raw.get("fetched_at"),
        "analysis_stocks_count": len(stocks),
    }

    out["portfolio"] = {
        "cash_dkk": round(cash, 2),
        "positions_value_dkk": round(positions_value, 2),
        "total_value_dkk": round(total_value, 2),
        "available_buy_budget_dkk": round(buy_budget, 2),
        "note": (
            "Behold altid min. 2.500 DKK kontant. available_buy_budget_dkk er en "
            "vejledende ramme pr. køb. Max 2 nye køb pr. dag. Ingen fast øvre grænse "
            "for positionsstørrelse — vurder selv koncentrations- og sektorrisiko."
        ),
    }

    # --- Åbne positioner med P&L og investment plan ---
    open_positions = []
    for p in positions:
        sym = p.get("symbol")
        buy_price = float(p.get("purchase_price") or 0)
        cur_price = float(
            prices.get(sym, {}).get("price")
            or p.get("current_price")
            or buy_price
        )
        shares = float(p.get("shares") or 0)
        pnl = pnl_pct(buy_price, cur_price)
        position_val = shares * cur_price

        stock_analysis = stocks.get(sym, {})
        plan = p.get("investment_plan", {})
        last_review = p.get("last_review", {})

        stop_loss = plan.get("stop_loss")
        stop_triggered = (cur_price <= float(stop_loss)) if stop_loss and cur_price else False

        open_positions.append({
            "symbol": sym,
            "name": p.get("name", sym),
            "shares": shares,
            "purchase_price": buy_price,
            "current_price": cur_price,
            "pnl_pct": round(pnl, 2) if pnl is not None else None,
            "position_value_dkk": round(position_val, 2),
            "weight_pct": round(position_val / total_value * 100, 1) if total_value else None,
            "purchase_date": p.get("purchase_date"),
            "stop_loss": stop_loss,
            "stop_loss_triggered": stop_triggered,
            "price_target": plan.get("price_target"),
            "investment_plan_thesis": plan.get("thesis"),
            "investment_plan_term": plan.get("term"),
            "investment_plan_exit_conditions": plan.get("exit_conditions"),
            "last_review_date": last_review.get("date"),
            "todays_verdict": stock_analysis.get("verdict"),
            "todays_confidence": stock_analysis.get("confidence"),
            "todays_bull": stock_analysis.get("bull", []),
            "todays_bear": stock_analysis.get("bear", []),
            "todays_summary": stock_analysis.get("summary"),
            "technical": compact_technical(prices, sym),
            "recent_news": knowledge_news(sym),
            "suggested_action": "VURDER SELL" if stop_triggered else "RE-EVALUER",
        })

    out["open_positions"] = open_positions

    # --- Analyserede aktier (kandidater til køb) ---
    candidates = []
    open_symbols = {p.get("symbol") for p in positions}
    for sym, stock in stocks.items():
        verdict = str(stock.get("verdict", "NEUTRAL")).upper()
        confidence = int(stock.get("confidence") or 0)
        cur_price = float(
            prices.get(sym, {}).get("price")
            or stock.get("price")
            or 0
        )
        has_position = sym in open_symbols
        shares_possible = floor(buy_budget / cur_price) if cur_price and buy_budget > 0 else 0

        candidates.append({
            "symbol": sym,
            "name": stock.get("name", sym),
            "verdict": verdict,
            "confidence": confidence,
            "price": cur_price,
            "sector": prices.get(sym, {}).get("sector"),
            "has_open_position": has_position,
            "shares_possible_with_budget": shares_possible,
            "cost_if_bought_dkk": round(shares_possible * cur_price, 2) if shares_possible else 0,
            "bull": stock.get("bull", []),
            "bear": stock.get("bear", []),
            "summary": stock.get("summary"),
            "key_risk": stock.get("key_risk"),
            "technical": compact_technical(prices, sym),
            "recent_news": knowledge_news(sym),
        })

    # Sorter: BULL først, derefter confidence
    candidates.sort(key=lambda x: (0 if x["verdict"] == "BULL" else 1, -x["confidence"]))
    out["analysis_candidates"] = candidates

    # Sektorfordeling af nuværende portefølje
    sector_weights: dict[str, float] = {}
    for op in open_positions:
        sec = prices.get(op["symbol"], {}).get("sector") or "Ukendt"
        sector_weights[sec] = sector_weights.get(sec, 0) + (op.get("weight_pct") or 0)
    out["sector_exposure_pct"] = {k: round(v, 1) for k, v in sector_weights.items()}

    out["instructions"] = (
        f"Du skal skrive decisions/{date_str}.json via github_store med dine beslutninger. "
        "Format: {date, market_summary, decisions: [{symbol, name, action, shares, price, confidence, "
        "reasoning, bull, bear, investment_plan: {term, basis, thesis, price_target, stop_loss, "
        "expected_return_pct, timeframe, exit_conditions}}]}. "
        "Brug recent_news og technical aktivt i din vurdering. "
        "sector_exposure_pct viser nuværende sektorfordeling — vurder selv koncentrationsrisiko. "
        "Alle åbne positioner SKAL have en entry (HOLD eller SELL). "
        "Derefter køres python paper_trader.py."
    )

    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
