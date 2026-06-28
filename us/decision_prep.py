"""
Decision Prep — prints portfolio + analysis to stdout (US S&P-500 bot).

Run: python decision_prep.py

Fetches us/analysis/YYYY-MM-DD.json, us/data.json and us/prices/latest.json from
GitHub, plus recent news and technical indicators per stock. Prints a compact
decision package to stdout so the trading routine can make qualified
BUY/SELL/HOLD decisions.
Output is written to us/decisions/YYYY-MM-DD.json by the routine itself.
"""
from __future__ import annotations

import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
from datetime import date
from math import floor

import github_store
from watchlist import YF_TO_NAME

_news_cache: dict[str, list] = {}

TECH_KEYS = (
    "rsi", "stoch", "bb_position", "macd_line", "atr",
    "sma50_vs_price", "sma200_vs_price", "momentum_5d",
    "momentum_20d", "momentum_divergence",
)

# ATR-based position sizing — risk 1.5% of total portfolio value
# per trade with stop-loss 2x ATR below entry price.
RISK_PER_TRADE_PCT = 0.015
ATR_STOP_MULTIPLIER = 2.0


def atr_position_size(total_value, cur_price, atr):
    """Return (suggested_shares, suggested_cost_usd, suggested_stop_usd) or (None, None, None)."""
    if not atr or not cur_price or not total_value:
        return None, None, None
    risk_budget = total_value * RISK_PER_TRADE_PCT
    risk_per_share = atr * ATR_STOP_MULTIPLIER
    if risk_per_share <= 0:
        return None, None, None
    shares = floor(risk_budget / risk_per_share)
    cost = round(shares * cur_price, 2)
    stop = round(cur_price - risk_per_share, 2)
    return shares, cost, stop


def today() -> str:
    return date.today().isoformat()


def pnl_pct(purchase_price, current_price):
    if not purchase_price or not current_price:
        return None
    return (float(current_price) / float(purchase_price) - 1) * 100


def knowledge_news(yf_sym, limit=6):
    """Recent news for a stock from the knowledge base (yfinance + news sources)."""
    if not yf_sym:
        return []
    if yf_sym in _news_cache:
        return _news_cache[yf_sym]
    safe = yf_sym.replace(".", "_").replace("/", "_").replace(" ", "_")
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
    _news_cache[yf_sym] = out
    return out


def compact_technical(prices, sym):
    t = (prices.get(sym, {}) or {}).get("technical") or {}
    return {k: t.get(k) for k in TECH_KEYS} if t else {}


def main() -> None:
    date_str = today()

    # --- Fetch data ---
    analysis, _ = github_store.get_json(f"analysis/{date_str}.json", default=None)
    data, _ = github_store.get_json("data.json", default={"portfolio": {"cash": 100000, "positions": []}, "trades": [], "history": []})
    prices_raw, _ = github_store.get_json("prices/latest.json", default={})
    prices = prices_raw.get("stocks", {})

    if not analysis:
        raise SystemExit(f"ERROR: No analysis/{date_str}.json — run the analysis routine first.")

    portfolio = data.get("portfolio", {})
    cash = float(portfolio.get("cash", 100000))
    positions = portfolio.get("positions", [])
    stocks = analysis.get("stocks", {})

    # Compute total portfolio value
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
        "cash_usd": round(cash, 2),
        "positions_value_usd": round(positions_value, 2),
        "total_value_usd": round(total_value, 2),
        "available_buy_budget_usd": round(buy_budget, 2),
        "note": (
            "Always keep min. 2,500 USD cash. available_buy_budget_usd is a "
            "guideline frame per buy. Max 2 new buys per day. No fixed upper limit "
            "on position size — assess concentration and sector risk yourself."
        ),
    }

    # --- Open positions with P&L and investment plan ---
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
            "position_value_usd": round(position_val, 2),
            "weight_pct": round(position_val / total_value * 100, 1) if total_value else None,
            "purchase_date": p.get("purchase_date"),
            "stop_loss": stop_loss,
            "stop_loss_triggered": stop_triggered,
            "price_target": plan.get("price_target"),
            "investment_plan_thesis": plan.get("thesis"),
            "investment_plan_term": plan.get("term"),
            "investment_plan_exit_conditions": plan.get("exit_conditions"),
            "last_review_date": last_review.get("date"),
            "next_earnings_date": prices.get(sym, {}).get("next_earnings_date"),
            "todays_verdict": stock_analysis.get("verdict"),
            "todays_confidence": stock_analysis.get("confidence"),
            "todays_bull": stock_analysis.get("bull", []),
            "todays_bear": stock_analysis.get("bear", []),
            "todays_summary": stock_analysis.get("summary"),
            "technical": compact_technical(prices, sym),
            "recent_news": knowledge_news(sym),
            "suggested_action": "CONSIDER SELL" if stop_triggered else "RE-EVALUATE",
        })

    out["open_positions"] = open_positions

    # --- Analyzed stocks (buy candidates) ---
    candidates = []
    open_symbols = {p.get("symbol") for p in positions}
    for sym, stock in stocks.items():
        verdict = str(stock.get("verdict", "NEUTRAL")).upper()
        confidence = int(stock.get("confidence") or 0)
        tier = str(stock.get("tier", "deep")).lower()
        cur_price = float(
            prices.get(sym, {}).get("price")
            or stock.get("price")
            or 0
        )
        has_position = sym in open_symbols
        shares_possible = floor(buy_budget / cur_price) if cur_price and buy_budget > 0 else 0
        tech = compact_technical(prices, sym)
        atr_val = tech.get("atr") if tech else None
        atr_shares, atr_cost, atr_stop = atr_position_size(total_value, cur_price, atr_val)

        candidates.append({
            "symbol": sym,
            "name": stock.get("name", YF_TO_NAME.get(sym, sym)),
            "tier": tier,
            "verdict": verdict,
            "confidence": confidence,
            "price": cur_price,
            "sector": prices.get(sym, {}).get("sector"),
            "has_open_position": has_position,
            "shares_possible_with_budget": shares_possible,
            "cost_if_bought_usd": round(shares_possible * cur_price, 2) if shares_possible else 0,
            "atr": atr_val,
            "suggested_shares_atr": atr_shares,
            "suggested_cost_usd_atr": atr_cost,
            "suggested_stop_usd_atr": atr_stop,
            "next_earnings_date": prices.get(sym, {}).get("next_earnings_date"),
            "bull": stock.get("bull", []),
            "bear": stock.get("bear", []),
            "summary": stock.get("summary"),
            "key_risk": stock.get("key_risk"),
            "technical": tech,
            "recent_news": knowledge_news(sym) if tier == "deep" else [],
        })

    # Sort: BULL first, then confidence
    candidates.sort(key=lambda x: (0 if x["verdict"] == "BULL" else 1, -x["confidence"]))
    out["analysis_candidates"] = candidates

    # Sector exposure of current portfolio
    sector_weights: dict[str, float] = {}
    for op in open_positions:
        sec = prices.get(op["symbol"], {}).get("sector") or "Unknown"
        sector_weights[sec] = sector_weights.get(sec, 0) + (op.get("weight_pct") or 0)
    out["sector_exposure_pct"] = {k: round(v, 1) for k, v in sector_weights.items()}

    out["sizing_methodology"] = {
        "risk_per_trade_pct": RISK_PER_TRADE_PCT * 100,
        "atr_stop_multiplier": ATR_STOP_MULTIPLIER,
        "note": (
            f"suggested_shares_atr is computed so the maximum loss at a 2x ATR stop = "
            f"{RISK_PER_TRADE_PCT*100:.1f}% of total portfolio value. "
            f"You may override, but use it as a starting point for position size."
        ),
    }

    out["instructions"] = (
        f"You must write decisions/{date_str}.json via github_store with your decisions. "
        "Format: {date, market_summary, decisions: [{symbol, name, action, shares, price, confidence, "
        "reasoning, bull, bear, investment_plan: {term, basis, thesis, price_target, stop_loss, "
        "expected_return_pct, timeframe, exit_conditions}}]}. "
        "Use recent_news and technical actively in your assessment. "
        "Position sizing: use suggested_shares_atr as a starting point (1.5% risk, 2x ATR stop). "
        "Material changes in fundamentals give free right to sell. "
        "next_earnings_date is shown on candidates — consider timing, but no trading ban. "
        "sector_exposure_pct shows current sector distribution — assess concentration risk yourself. "
        "Tier-based analysis: 'deep' = thorough + recent_news, 'scan' = short assessment without news. "
        "All open positions MUST have an entry (HOLD or SELL). "
        "Then run python paper_trader.py."
    )

    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
