"""
Trade Review — post-mortem på lukkede handler (læringsloop).

Kør: python trade_review.py            (i execute_decisions-workflowet, efter paper_trader)
     python trade_review.py --selftest

For hver SELL i data.json trades[] uden en eksisterende lesson:
  1. find købsdatoen (seneste forudgående BUY i trades[]; fallback: dato - holding_days),
  2. slå den oprindelige investment_plan op i decisions/KØBSDATO.json,
  3. sammenlign antagelserne (price_target, stop_loss, expected_return_pct, timeframe)
     med det faktiske udfald (realized_pnl_pct, holding_days, exit-pris),
  4. skriv én lesson-række til lessons.json + genberegn aggregeret statistik.

decision_prep.py sender stats + seneste lessons med i beslutningspakken, så
handels-AI'en ser sit eget track record. Ren stdlib, ingen AI — mekanisk dom:
  HOLDT       kursmål ramt, eller realiseret afkast >= forventet
  DELVIST     gevinst, men under det forventede (eller ingen målbar antagelse)
  HOLDT IKKE  tab
  UKENDT      mangler realiseret P&L
"""
from __future__ import annotations

import sys
from datetime import date, timedelta

import github_store

PREFIX = ""  # us-botten bruger "us/"
CCY = "dkk"
LESSONS_PATH = f"{PREFIX}lessons.json"
DATA_PATH = f"{PREFIX}data.json"
PRICES_PATH = f"{PREFIX}prices/latest.json"
DECISIONS_DIR = f"{PREFIX}decisions"
MAX_LESSONS = 500

VERDICT_HELD = "HOLDT"
VERDICT_PARTIAL = "DELVIST"
VERDICT_FAILED = "HOLDT IKKE"
VERDICT_UNKNOWN = "UKENDT"

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
    """Seneste forudgående BUY for samme symbol. Ved add-on køb er det netop det
    seneste BUY hvis investment_plan positionen bar ved exit (paper_trader
    overskriver planen ved add-on). Fallback: regn baglæns fra holding_days
    (dækker BUYs der er røget ud af trades[] pga. MAX_TRADES-cappen)."""
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
    """Oprindelig investment_plan fra decisions/KØBSDATO.json (tom dict hvis væk)."""
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
    """Mekanisk dom: (target_hit, stop_hit, verdict). None = antagelsen var ikke sat."""
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
        return f"{sym}: udfald ukendt (mangler realiseret P&L)."
    parts = [f"{sym}: {realized_pct:+.1f}% på {holding_days if holding_days is not None else '?'} dage — antagelse {verdict}."]
    if expected is not None:
        parts.append(f"Forventet {expected:+.1f}%.")
    if timeframe:
        parts.append(f"Plan-horisont: {timeframe}.")
    if stop_hit:
        parts.append("Exit på/under stop-loss.")
    elif target_hit:
        parts.append("Kursmål nået.")
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
        sec = l.get("sector") or "Ukendt"
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
        print("[trade_review] Ingen nye lukkede handler at gennemgå.")
        return

    lessons = lessons[-MAX_LESSONS:]
    out = {
        "updated": date.today().isoformat(),
        "stats": build_stats(lessons),
        "lessons": lessons,
    }
    github_store.put_json(LESSONS_PATH, out, f"Trade review: {new} nye lessons ({date.today().isoformat()})")
    print(f"[trade_review] {new} nye lessons, {len(lessons)} i alt. "
          f"Win rate: {out['stats'].get('win_rate_pct')}% | "
          f"Domme: {out['stats'].get('thesis_verdicts')}")


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
         "sector": "Health", "thesis_verdict": VERDICT_HELD, "target_hit": True, "stop_hit": False},
        {"realized_pnl_pct": -4.0, f"realized_pnl_{CCY}": -40, "holding_days": 15,
         "sector": "Health", "thesis_verdict": VERDICT_FAILED, "target_hit": False, "stop_hit": True},
    ])
    assert stats["closed_trades"] == 2 and stats["wins"] == 1 and stats["win_rate_pct"] == 50.0
    assert stats["by_sector"]["Health"]["avg_pnl_pct"] == 3.0
    assert stats["target_hits"] == 1 and stats["stop_hits"] == 1
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        main()
