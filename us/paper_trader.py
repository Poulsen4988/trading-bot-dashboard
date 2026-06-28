"""
Paper Trader — dumb executor (US S&P 500).

Reads us/decisions/YYYY-MM-DD.json (AI output from the trading routine) and
executes the decisions mechanically against us/data.json.

No trading rules here — all decision logic lives in the AI routine.
HOLD is logged as a recommendation in trades (shown in the dashboard
Recommendations tab) but does not affect cash or positions.
"""
from __future__ import annotations

import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import date, datetime, timezone
from math import floor

import github_store

INITIAL_CASH = 100_000

# Growth control for data.json (dashboard payload). The full rationale (bull/bear,
# investment_plan, full summary) ALWAYS lives in us/decisions/DATE.json, which the
# dashboard modal fetches on-demand. In trades we keep only a light summary, so the
# file stays small. History is capped to ~2 years; trade count to MAX_TRADES.
TRADE_SUMMARY_CAP = 240
MAX_HISTORY_POINTS = 730
MAX_TRADES = 600


def slim_trades(data):
    """Slim each trade's reasoning to {verdict, confidence, summary} and drop
    investment_plan + bull/bear lists. Keep the most recent MAX_TRADES rows.
    Idempotent. Full detail lives in us/decisions/DATE.json."""
    for t in data.get("trades", []):
        t.pop("investment_plan", None)
        r = t.get("reasoning")
        if isinstance(r, dict):
            slim = {"verdict": r.get("verdict")}
            if r.get("confidence") is not None:
                slim["confidence"] = r.get("confidence")
            summary = (r.get("summary") or "")[:TRADE_SUMMARY_CAP]
            if summary:
                slim["summary"] = summary
            t["reasoning"] = slim
    trades = data.get("trades", [])
    if len(trades) > MAX_TRADES:
        data["trades"] = trades[-MAX_TRADES:]
    return data


def cap_history(data, limit=MAX_HISTORY_POINTS):
    hist = data.get("history", [])
    if len(hist) > limit:
        data["history"] = hist[-limit:]
    return data


def today():
    return date.today().isoformat()


def default_data():
    return {
        "portfolio": {
            "initial_cash": INITIAL_CASH,
            "cash": INITIAL_CASH,
            "currency": "USD",
            "positions": [],
        },
        "history": [],
        "trades": [],
    }


def position_value(position, prices=None):
    price = None
    if prices:
        price = prices.get(position.get("symbol", ""), {}).get("price")
    price = price or position.get("current_price") or position.get("purchase_price")
    return float(position.get("shares", 0)) * float(price or 0)


def portfolio_value(data, prices=None):
    p = data.get("portfolio", {})
    cash = float(p.get("cash", INITIAL_CASH))
    return cash + sum(position_value(pos, prices) for pos in p.get("positions", []))


def find_position(data, sym):
    for p in data.get("portfolio", {}).get("positions", []):
        if p.get("symbol") == sym:
            return p
    return None


def next_trade_id(data):
    return max([int(t.get("id", 0)) for t in data.get("trades", [])] + [0]) + 1


def add_trade(data, trade):
    for t in data.setdefault("trades", []):
        t["is_new"] = False
    trade["id"] = next_trade_id(data)
    trade["is_new"] = True
    data["trades"].append(trade)


def execute_decisions(decisions_data, data):
    date_str = decisions_data.get("date") or today()
    decisions = decisions_data.get("decisions", [])

    portfolio = data.setdefault("portfolio", {})
    portfolio.setdefault("initial_cash", INITIAL_CASH)
    portfolio.setdefault("cash", INITIAL_CASH)
    portfolio.setdefault("currency", "USD")
    positions = portfolio.setdefault("positions", [])

    executed = []
    holds = []

    for decision in decisions:
        sym = decision.get("symbol")
        if not sym:
            continue
        action = str(decision.get("action", "HOLD")).upper()
        shares = int(decision.get("shares") or 0)
        price = decision.get("price")
        price = float(price) if price else None
        name = decision.get("name", sym)
        investment_plan = decision.get("investment_plan", {})
        reasoning_text = decision.get("reasoning", "")
        confidence = decision.get("confidence")
        bull = decision.get("bull", [])
        bear = decision.get("bear", [])

        pos = find_position(data, sym)
        skip_reason = None
        realized_pnl_usd = None
        realized_pnl_pct = None
        holding_days = None
        cost_basis = None

        if action == "BUY":
            if not price or shares <= 0:
                skip_reason = "BUY rejected: missing price or shares."
                action = "HOLD"
            else:
                cost = round(shares * price, 2)
                cash = float(portfolio.get("cash", 0))
                if cost > cash:
                    shares = floor(cash / price)
                    if shares <= 0:
                        skip_reason = f"BUY rejected: not enough cash (${cash:.0f})."
                        action = "HOLD"
                    else:
                        cost = round(shares * price, 2)

                if action == "BUY":
                    portfolio["cash"] = round(float(portfolio.get("cash", 0)) - cost, 2)
                    if pos:
                        old_shares = float(pos.get("shares", 0))
                        old_price = float(pos.get("purchase_price", price))
                        new_shares = old_shares + shares
                        avg_price = round((old_shares * old_price + shares * price) / new_shares, 4)
                        pos["shares"] = new_shares
                        pos["purchase_price"] = avg_price
                        pos["current_price"] = price
                        pos["investment_plan"] = investment_plan
                        pos["last_review"] = {
                            "date": date_str,
                            "reasoning": reasoning_text,
                            "confidence": confidence,
                        }
                    else:
                        positions.append({
                            "symbol": sym,
                            "name": name,
                            "shares": shares,
                            "purchase_price": price,
                            "current_price": price,
                            "purchase_date": date_str,
                            "investment_plan": investment_plan,
                            "last_review": {
                                "date": date_str,
                                "reasoning": reasoning_text,
                                "confidence": confidence,
                            },
                        })

        elif action == "SELL":
            if not pos:
                skip_reason = f"SELL rejected: no open position in {sym}."
                action = "HOLD"
            else:
                sell_price = price or pos.get("current_price") or pos.get("purchase_price")
                sell_price = float(sell_price)
                sell_shares = shares if 0 < shares <= int(pos.get("shares", 0)) else int(pos.get("shares", 0))
                proceeds = round(sell_shares * sell_price, 2)
                buy_price = float(pos.get("purchase_price") or 0)
                cost_basis = round(buy_price * sell_shares, 2) if buy_price else None
                realized_pnl_usd = round((sell_price - buy_price) * sell_shares, 2) if buy_price else None
                realized_pnl_pct = round((sell_price / buy_price - 1) * 100, 2) if buy_price else None
                purchase_date = pos.get("purchase_date")
                if purchase_date:
                    try:
                        d_buy = date.fromisoformat(purchase_date)
                        d_sell = date.fromisoformat(date_str) if isinstance(date_str, str) else date.today()
                        holding_days = (d_sell - d_buy).days
                    except Exception:
                        holding_days = None
                portfolio["cash"] = round(float(portfolio.get("cash", 0)) + proceeds, 2)
                if sell_shares >= int(pos.get("shares", 0)):
                    positions.remove(pos)
                else:
                    pos["shares"] = int(pos.get("shares", 0)) - sell_shares
                    pos["current_price"] = sell_price
                shares = sell_shares
                price = sell_price

        if action == "HOLD":
            if pos:
                if price:
                    pos["current_price"] = price
                pos["last_review"] = {
                    "date": date_str,
                    "reasoning": reasoning_text,
                    "confidence": confidence,
                }
                if investment_plan:
                    pos["investment_plan"] = investment_plan
            holds.append({"symbol": sym, "skip_reason": skip_reason})
            # Log genuine HOLDs (not failed BUY/SELLs) to trades for dashboard Recommendations
            if not skip_reason:
                already_logged = any(
                    t.get("date") == date_str and t.get("symbol") == sym and t.get("action") == "HOLD"
                    for t in data.get("trades", [])
                )
                if not already_logged:
                    hold_trade = {
                        "date": date_str,
                        "action": "HOLD",
                        "symbol": sym,
                        "name": name,
                        "shares": None,
                        "price": price,
                        "value": None,
                        "reasoning": {
                            "verdict": "HOLD",
                            "summary": reasoning_text,
                            "confidence": confidence,
                            "bull": bull,
                            "bear": bear,
                        },
                        "investment_plan": investment_plan,
                    }
                    add_trade(data, hold_trade)
            continue

        value = round((shares or 0) * (price or 0), 2)
        trade = {
            "date": date_str,
            "action": action,
            "symbol": sym,
            "name": name,
            "shares": shares,
            "price": price,
            "value": value,
            "reasoning": {
                "verdict": action,
                "summary": reasoning_text,
                "confidence": confidence,
                "bull": bull,
                "bear": bear,
            },
            "investment_plan": investment_plan,
        }
        if action == "SELL":
            trade["cost_basis_usd"] = cost_basis
            trade["realized_pnl_usd"] = realized_pnl_usd
            trade["realized_pnl_pct"] = realized_pnl_pct
            trade["holding_days"] = holding_days
        add_trade(data, trade)
        executed.append(trade)

    # Update history
    prices_map = {
        d.get("symbol"): {"price": d.get("price")}
        for d in decisions
        if d.get("price")
    }
    new_total = round(portfolio_value(data, prices_map), 2)
    history = data.setdefault("history", [])
    history = [h for h in history if h.get("date") != date_str]
    history.append({"date": date_str, "portfolio_value": new_total})
    data["history"] = history
    portfolio["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return executed, holds, new_total


def main():
    date_str = today()

    decisions_data, _ = github_store.get_json(
        f"us/decisions/{date_str}.json", default=None, raise_on_error=True
    )
    if not decisions_data:
        raise SystemExit(
            f"No us/decisions/{date_str}.json found. "
            "The trading routine must write this file before paper_trader.py runs."
        )

    # raise_on_error: better to stop than trade against an empty/stale portfolio and
    # overwrite good remote state on a transient read error.
    data, _ = github_store.get_json("us/data.json", default=default_data(), raise_on_error=True)
    executed, holds, new_total = execute_decisions(decisions_data, data)

    # Print full summary (with thesis) BEFORE slimming.
    print(f"=== PAPER TRADE SUMMARY {date_str} ===")
    for t in executed:
        plan = t.get("investment_plan", {}) or {}
        print(
            f"{t['action']:4} {t['symbol']:14} "
            f"shares={t['shares']} price={t['price']} value=${t['value']}"
        )
        if plan.get("thesis"):
            print(f"     Thesis: {plan['thesis'][:120]}")
        if plan.get("stop_loss"):
            print(f"     Stop-loss: {plan['stop_loss']} | Target: {plan.get('price_target', '?')} | Timeframe: {plan.get('timeframe', '?')}")
    for h in holds:
        line = f"HOLD {h['symbol']}"
        if h.get("skip_reason"):
            line += f" — {h['skip_reason']}"
        print(line)
    print(f"\nNew portfolio value: ${new_total}")

    # Slim to dashboard payload and write. Full detail is already in us/decisions/.
    slim_trades(data)
    cap_history(data)
    ok = github_store.put_json("us/data.json", data, f"US paper trades {date_str}")
    if github_store.TOKEN and not ok:
        raise SystemExit("us/data.json could not be written to GitHub — trades NOT saved. See error above.")


if __name__ == "__main__":
    main()
