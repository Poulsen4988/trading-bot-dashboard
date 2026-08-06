"""
Trade Review — post-mortem on closed trades (learning loop, US S&P-500 bot).

Run: python us/trade_review.py            (in the execute_decisions workflow, after paper_trader)
     python us/trade_review.py --selftest

For every SELL in us/data.json trades[] without an existing lesson:
  1. find the buy date (latest preceding BUY in trades[]; fallback: date - holding_days),
  2. look up the original investment_plan in us/decisions/BUYDATE.json,
  3. compare the assumptions (price_target, stop_loss, expected_return_pct, timeframe)
     with the actual outcome (realized_pnl_pct, holding_days, exit price),
  4. append one lesson row to us/lessons.json + recompute aggregate stats.

decision_prep.py includes stats + recent lessons in the decision package so the
trading AI sees its own track record. Pure stdlib, no AI — mechanical verdict:
  HELD     price target hit, or realized return >= expected
  PARTIAL  gain, but below expectation (or no measurable assumption)
  FAILED   loss
  UNKNOWN  realized P&L missing
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import github_store

PREFIX = "us/"
CCY = "usd"
LESSONS_PATH = f"{PREFIX}lessons.json"
DATA_PATH = f"{PREFIX}data.json"
PRICES_PATH = f"{PREFIX}prices/latest.json"
DECISIONS_DIR = f"{PREFIX}decisions"
MAX_LESSONS = 500

VERDICT_HELD = "HELD"
VERDICT_PARTIAL = "PARTIAL"
VERDICT_FAILED = "FAILED"
VERDICT_UNKNOWN = "UNKNOWN"

_decisions_cache: dict[str, dict] = {}


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def trade_key(t: dict) -> str:
    tid = t.get("id")
    if tid is not None:
        return f"id:{tid}"
    return f"{t.get('date')}|{t.get('symbol')}|{t.get('shares')}|{t.get('price')}"


def find_buy_date(trades: list, sell_idx: int):
    """Latest preceding BUY for the same symbol. For add-on buys that is exactly
    the BUY whose investment_plan the position carried at exit (paper_trader
    overwrites the plan on add-ons). Fallback: compute back from holding_days
    (covers BUYs pruned from trades[] by the MAX_TRADES cap)."""
    sym = trades[sell_idx].get("symbol")
    for j in range(sell_idx - 1, -1, -1):
        t = trades[j]
        if t.get("symbol") == sym and str(t.get("action", "")).upper() == "BUY":
            return t.get("date")
    hd = trades[sell_idx].get("holding_days")
    d = trades[sell_idx].get("date")
    if hd is not None and d:
        try:
            return (date.fromisoformat(str(d)[:10]) - timedelta(days=int(hd))).isoformat()
        except Exception:
            return None
    return None


def buy_plan(sym: str, buy_date: str | None) -> dict:
    """Original investment_plan from us/decisions/BUYDATE.json (empty dict if gone)."""
    if not buy_date:
        return {}
    if buy_date not in _decisions_cache:
        doc, _ = github_store.get_json(f"{DECISIONS_DIR}/{buy_date}.json", default={})
        _decisions_cache[buy_date] = doc or {}
    for d in _decisions_cache[buy_date].get("decisions", []):
        if d.get("symbol") == sym and str(d.get("action", "")).upper() == "BUY":
            return d.get("investment_plan") or {}
    return {}


def evaluate(sell_price, realized_pct, plan: dict):
    """Mechanical verdict: (target_hit, stop_hit, verdict). None = assumption not set."""
    target = _f(plan.get("price_target"))
    stop = _f(plan.get("stop_loss"))
    expected = _f(plan.get("expected_return_pct"))
    target_hit = None if (target is None or sell_price is None) else sell_price >= target
    stop_hit = None if (stop is None or sell_price is None) else sell_price <= stop
    if realized_pct is None:
        verdict = VERDICT_UNKNOWN
    elif target_hit or (expected is not None and realized_pct >= expected):
        verdict = VERDICT_HELD
    elif realized_pct > 0:
        verdict = VERDICT_PARTIAL
    else:
        verdict = VERDICT_FAILED
    return target_hit, stop_hit, verdict


def lesson_text(sym, realized_pct, holding_days, timeframe, target_hit, stop_hit, verdict, expected):
    if realized_pct is None:
        return f"{sym}: outcome unknown (realized P&L missing)."
    parts = [f"{sym}: {realized_pct:+.1f}% over {holding_days if holding_days is not None else '?'} days — assumption {verdict}."]
    if expected is not None:
        parts.append(f"Expected {expected:+.1f}%.")
    if timeframe:
        parts.append(f"Plan horizon: {timeframe}.")
    if stop_hit:
        parts.append("Exited at/below stop-loss.")
    elif target_hit:
        parts.append("Price target reached.")
    return " ".join(parts)


def build_stats(lessons: list) -> dict:
    pnls = [l["realized_pnl_pct"] for l in lessons if l.get("realized_pnl_pct") is not None]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    hold = [l["holding_days"] for l in lessons if l.get("holding_days") is not None]
    verdicts: dict[str, int] = {}
    by_sector: dict[str, dict] = {}
    for l in lessons:
        verdicts[l.get("thesis_verdict") or VERDICT_UNKNOWN] = verdicts.get(l.get("thesis_verdict") or VERDICT_UNKNOWN, 0) + 1
        sec = l.get("sector") or "Unknown"
        b = by_sector.setdefault(sec, {"n": 0, "wins": 0, "_sum": 0.0, "_n_pnl": 0})
        b["n"] += 1
        p = l.get("realized_pnl_pct")
        if p is not None:
            b["_sum"] += p
            b["_n_pnl"] += 1
            if p > 0:
                b["wins"] += 1
    for b in by_sector.values():
        n_pnl = b.pop("_n_pnl")
        s = b.pop("_sum")
        b["avg_pnl_pct"] = round(s / n_pnl, 2) if n_pnl else None
    return {
        "closed_trades": len(lessons),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(len(wins) / len(pnls) * 100, 1) if pnls else None,
        "avg_win_pct": round(sum(wins) / len(wins), 2) if wins else None,
        "avg_loss_pct": round(sum(losses) / len(losses), 2) if losses else None,
        "avg_pnl_pct": round(sum(pnls) / len(pnls), 2) if pnls else None,
        "avg_holding_days": round(sum(hold) / len(hold), 1) if hold else None,
        f"total_realized_{CCY}": round(sum(l.get(f"realized_pnl_{CCY}") or 0 for l in lessons), 2),
        "target_hits": sum(1 for l in lessons if l.get("target_hit")),
        "stop_hits": sum(1 for l in lessons if l.get("stop_hit")),
        "thesis_verdicts": verdicts,
        "by_sector": by_sector,
    }


def main() -> None:
    data, _ = github_store.get_json(DATA_PATH, default={})
    trades = (data or {}).get("trades", [])
    doc, _ = github_store.get_json(LESSONS_PATH, default={})
    lessons = (doc or {}).get("lessons", [])
    seen = {l.get("trade_key") for l in lessons}

    prices_raw, _ = github_store.get_json(PRICES_PATH, default={})
    sectors = {s: (v or {}).get("sector") for s, v in (prices_raw or {}).get("stocks", {}).items()}

    new = 0
    for i, t in enumerate(trades):
        if str(t.get("action", "")).upper() != "SELL":
            continue
        key = trade_key(t)
        if key in seen:
            continue
        sym = t.get("symbol")
        sell_price = _f(t.get("price"))
        realized_pct = _f(t.get("realized_pnl_pct"))
        bd = find_buy_date(trades, i)
        plan = buy_plan(sym, bd)
        target_hit, stop_hit, verdict = evaluate(sell_price, realized_pct, plan)
        expected = _f(plan.get("expected_return_pct"))
        shares = _f(t.get("shares"))
        cost_basis = _f(t.get(f"cost_basis_{CCY}"))
        lessons.append({
            "trade_key": key,
            "date": t.get("date"),
            "symbol": sym,
            "name": t.get("name"),
            "sector": sectors.get(sym),
            "buy_date": bd,
            "holding_days": t.get("holding_days"),
            "shares": t.get("shares"),
            "buy_price": round(cost_basis / shares, 4) if cost_basis and shares else None,
            "sell_price": sell_price,
            f"realized_pnl_{CCY}": t.get(f"realized_pnl_{CCY}"),
            "realized_pnl_pct": realized_pct,
            "expected_return_pct": expected,
            "price_target": _f(plan.get("price_target")),
            "stop_loss": _f(plan.get("stop_loss")),
            "timeframe": plan.get("timeframe"),
            "term": plan.get("term"),
            "thesis": plan.get("thesis"),
            "target_hit": target_hit,
            "stop_hit": stop_hit,
            "thesis_verdict": verdict,
            "lesson": lesson_text(sym, realized_pct, t.get("holding_days"), plan.get("timeframe"),
                                  target_hit, stop_hit, verdict, expected),
        })
        seen.add(key)
        new += 1

    if not new:
        print("[trade_review] No new closed trades to review.")
        return

    lessons = lessons[-MAX_LESSONS:]
    out = {
        "updated": date.today().isoformat(),
        "stats": build_stats(lessons),
        "lessons": lessons,
    }
    github_store.put_json(LESSONS_PATH, out, f"Trade review (US): {new} new lessons ({date.today().isoformat()})")
    print(f"[trade_review] {new} new lessons, {len(lessons)} total. "
          f"Win rate: {out['stats'].get('win_rate_pct')}% | "
          f"Verdicts: {out['stats'].get('thesis_verdicts')}")


def selftest() -> None:
    assert evaluate(110.0, 12.0, {"price_target": 105, "expected_return_pct": 10}) == (True, None, VERDICT_HELD)
    assert evaluate(104.0, 4.0, {"price_target": 110, "expected_return_pct": 10}) == (False, None, VERDICT_PARTIAL)
    assert evaluate(90.0, -8.0, {"price_target": 110, "stop_loss": 92}) == (False, True, VERDICT_FAILED)
    assert evaluate(100.0, None, {}) == (None, None, VERDICT_UNKNOWN)
    assert evaluate(100.0, 5.0, {}) == (None, None, VERDICT_PARTIAL)
    assert evaluate(100.0, 15.0, {"expected_return_pct": 10}) == (None, None, VERDICT_HELD)
    t = [
        {"symbol": "X", "action": "BUY", "date": "2026-01-02"},
        {"symbol": "Y", "action": "BUY", "date": "2026-01-05"},
        {"symbol": "X", "action": "SELL", "date": "2026-02-01", "holding_days": 30},
    ]
    assert find_buy_date(t, 2) == "2026-01-02"
    assert find_buy_date([t[2]], 0) == "2026-01-02"  # fallback via holding_days
    assert find_buy_date([{"symbol": "X", "action": "SELL", "date": "2026-02-01"}], 0) is None
    stats = build_stats([
        {"realized_pnl_pct": 10.0, f"realized_pnl_{CCY}": 100, "holding_days": 5,
         "sector": "Tech", "thesis_verdict": VERDICT_HELD, "target_hit": True, "stop_hit": False},
        {"realized_pnl_pct": -4.0, f"realized_pnl_{CCY}": -40, "holding_days": 15,
         "sector": "Tech", "thesis_verdict": VERDICT_FAILED, "target_hit": False, "stop_hit": True},
    ])
    assert stats["closed_trades"] == 2 and stats["wins"] == 1 and stats["win_rate_pct"] == 50.0
    assert stats["by_sector"]["Tech"]["avg_pnl_pct"] == 3.0
    assert stats["target_hits"] == 1 and stats["stop_hits"] == 1
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        main()
