"""
Trader Agent til virtuel paper trading.

Kør: python paper_trader.py

Læser analysis/YYYY-MM-DD.json og data.json, anvender paper-trading-regler,
opdaterer data.json og printer beslutningerne.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from math import floor

import github_store

INITIAL_CASH = 100_000
MAX_SINGLE_BUY_WEIGHT = 0.25
MIN_CASH_AFTER_BUY = 2_500
MIN_BUY_CONFIDENCE = 65
MIN_SELL_CONFIDENCE = 60
REVIEW_STOP_LOSS_PCT = -8.0
MAX_BUYS_PER_DAY = 1


def today():
    return date.today().isoformat()


def default_data():
    return {
        "portfolio": {"initial_cash": INITIAL_CASH, "cash": INITIAL_CASH, "currency": "DKK", "positions": []},
        "history": [],
        "trades": [],
    }


def position_value(position, prices):
    sym = position["symbol"]
    price = prices.get(sym, {}).get("price") or position.get("current_price") or position.get("purchase_price")
    return float(position.get("shares", 0)) * float(price or 0)


def portfolio_value(data, prices):
    p = data.get("portfolio", {})
    cash = float(p.get("cash", INITIAL_CASH))
    return cash + sum(position_value(pos, prices) for pos in p.get("positions", []))


def find_position(data, sym):
    for p in data.get("portfolio", {}).get("positions", []):
        if p.get("symbol") == sym:
            return p
    return None


def pnl_pct(position, price):
    purchase = float(position.get("purchase_price") or 0)
    if not purchase or price is None:
        return None
    return (float(price) / purchase - 1) * 100


def next_trade_id(data):
    return max([int(t.get("id", 0)) for t in data.get("trades", [])] + [0]) + 1


def add_trade(data, trade):
    for t in data.setdefault("trades", []):
        t["is_new"] = False
    trade["id"] = next_trade_id(data)
    trade["is_new"] = True
    data["trades"].append(trade)


def reasoning_from_analysis(stock):
    return {
        "bull": stock.get("bull", []),
        "bear": stock.get("bear", []),
        "verdict": stock.get("verdict"),
        "confidence": stock.get("confidence"),
        "summary": stock.get("summary"),
        "key_risk": stock.get("key_risk"),
    }


def make_trade(date_str, action, sym, stock, shares, price, reason):
    value = round((shares or 0) * (price or 0), 2)
    r = reasoning_from_analysis(stock)
    r["trade_reason"] = reason
    return {
        "date": date_str,
        "action": action,
        "symbol": sym,
        "name": stock.get("name", sym),
        "shares": shares,
        "price": price,
        "value": value,
        "reasoning": r,
    }


def apply_decisions(analysis, data):
    date_str = analysis.get("date") or today()
    stocks = analysis.get("stocks", {})
    prices = {sym: s for sym, s in stocks.items()}
    portfolio = data.setdefault("portfolio", {})
    portfolio.setdefault("initial_cash", INITIAL_CASH)
    portfolio.setdefault("cash", INITIAL_CASH)
    portfolio.setdefault("currency", "DKK")
    positions = portfolio.setdefault("positions", [])

    total_value = portfolio_value(data, prices)
    buys_done = 0
    decisions = []

    # Først vurder alle analyserede aktier.
    for sym, stock in stocks.items():
        verdict = str(stock.get("verdict", "NEUTRAL")).upper()
        confidence = int(stock.get("confidence") or 0)
        price = stock.get("price")
        price = float(price) if price else None
        pos = find_position(data, sym)

        action = "HOLD"
        shares = 0
        reason = "Ingen stærk nok edge til at ændre porteføljen."

        if pos:
            p = pnl_pct(pos, price)
            if verdict == "BEAR" and confidence >= MIN_SELL_CONFIDENCE:
                action = "SELL"
                shares = int(pos.get("shares", 0))
                reason = f"BEAR verdict med confidence {confidence}; thesis bør lukkes/reduceres."
            elif p is not None and p <= REVIEW_STOP_LOSS_PCT and verdict != "BULL":
                action = "SELL"
                shares = int(pos.get("shares", 0))
                reason = f"Positionen er nede {round(p,2)}% og analysen er ikke BULL."
            else:
                reason = "Eksisterende position beholdes; ingen klar sell-trigger."

        elif verdict == "BULL" and confidence >= MIN_BUY_CONFIDENCE and buys_done < MAX_BUYS_PER_DAY and price:
            cash = float(portfolio.get("cash", 0))
            trade_budget = min(total_value * MAX_SINGLE_BUY_WEIGHT, max(0, cash - MIN_CASH_AFTER_BUY))
            shares = floor(trade_budget / price) if price else 0
            if shares > 0:
                action = "BUY"
                buys_done += 1
                reason = f"BULL verdict med confidence {confidence}; position sizing maks {MAX_SINGLE_BUY_WEIGHT:.0%} af porteføljen."
            else:
                reason = "BULL case, men for lidt kontantbeholdning til ny position."

        if action == "BUY":
            cost = round(shares * price, 2)
            portfolio["cash"] = round(float(portfolio.get("cash", 0)) - cost, 2)
            positions.append({
                "symbol": sym,
                "name": stock.get("name", sym),
                "shares": shares,
                "purchase_price": price,
                "current_price": price,
                "purchase_date": date_str,
            })
        elif action == "SELL" and pos:
            proceeds = round(shares * price, 2) if price else 0
            portfolio["cash"] = round(float(portfolio.get("cash", 0)) + proceeds, 2)
            positions.remove(pos)

        trade = make_trade(date_str, action, sym, stock, shares, price, reason)
        add_trade(data, trade)
        decisions.append(trade)

    # Stop-loss review for positioner der ikke indgår i dagens analyse.
    analyzed = set(stocks.keys())
    for pos in list(positions):
        sym = pos.get("symbol")
        if sym in analyzed:
            continue
        price = pos.get("current_price") or pos.get("purchase_price")
        p = pnl_pct(pos, price)
        if p is not None and p <= REVIEW_STOP_LOSS_PCT:
            shares = int(pos.get("shares", 0))
            stock = {"name": pos.get("name", sym), "price": price, "verdict": "RISK_REVIEW", "confidence": 0, "summary": "Stop-loss review uden dagens dybanalyse."}
            proceeds = round(shares * float(price), 2)
            portfolio["cash"] = round(float(portfolio.get("cash", 0)) + proceeds, 2)
            positions.remove(pos)
            trade = make_trade(date_str, "SELL", sym, stock, shares, float(price), f"Ikke analyseret i dag og nede {round(p,2)}%.")
            add_trade(data, trade)
            decisions.append(trade)

    # Opdater aktuelle priser for positioner der blev analyseret.
    for pos in positions:
        sym = pos.get("symbol")
        if sym in stocks and stocks[sym].get("price"):
            pos["current_price"] = stocks[sym]["price"]

    new_total = round(portfolio_value(data, prices), 2)
    history = data.setdefault("history", [])
    history = [h for h in history if h.get("date") != date_str]
    history.append({"date": date_str, "portfolio_value": new_total})
    data["history"] = history
    portfolio["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return decisions, new_total


def main():
    date_str = today()
    analysis, _ = github_store.get_json(f"analysis/{date_str}.json", default=None)
    if not analysis:
        raise SystemExit(f"Ingen analysis/{date_str}.json fundet. Kør analyst-routinen først.")

    data, _ = github_store.get_json("data.json", default=default_data())
    decisions, new_total = apply_decisions(analysis, data)
    github_store.put_json("data.json", data, f"Paper trades {date_str}")

    print("=== PAPER TRADE SUMMARY ===")
    for d in decisions:
        print(f"{d['action']} {d['symbol']} shares={d['shares']} price={d['price']} value={d['value']} — {d['reasoning'].get('trade_reason')}")
    print(f"Ny porteføljeværdi: {new_total} DKK")


if __name__ == "__main__":
    main()
