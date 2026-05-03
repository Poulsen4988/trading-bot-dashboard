"""
Risikostyring for analyse-botten.

Denne fil er bevidst deterministisk: AI'en må foreslå BUY/SELL/HOLD,
men koden normaliserer og annoterer beslutningen, før den logges.
Der sendes ingen live-ordrer herfra.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from watchlist import WATCHLIST

VALID_ACTIONS = {"BUY", "SELL", "HOLD", "REVIEW"}
KNOWN_BY_UIC = {s["uic"]: s for s in WATCHLIST if s.get("uic") is not None}
KNOWN_BY_SYMBOL = {s["symbol"]: s for s in WATCHLIST}

# Bløde porteføljeregler til analyseforslag. Det er ikke hårde Saxo-regler.
MAX_SINGLE_IDEA_WEIGHT = 0.25
REVIEW_LOSS_PCT = -8.0
TAKE_PROFIT_REVIEW_PCT = 20.0


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _portfolio_value(market: dict[str, Any]) -> float:
    account = market.get("account") or {}
    cash = _to_float(account.get("cash"), 0.0)
    positions = market.get("positions") or []
    pos_value = 0.0
    for p in positions:
        shares = _to_float(p.get("shares") or p.get("amount"), 0.0)
        price = _to_float(p.get("current_price") or p.get("price"), 0.0)
        pos_value += shares * price
    return cash + pos_value


def _open_positions(market: dict[str, Any]) -> list[dict[str, Any]]:
    return [p for p in (market.get("positions") or []) if _to_float(p.get("shares") or p.get("amount"), 0) != 0]


def _find_quote(market: dict[str, Any], symbol: str | None = None, uic: int | None = None) -> dict[str, Any] | None:
    for q in market.get("quotes") or []:
        if uic is not None and q.get("uic") == uic:
            return q
        if symbol and (q.get("symbol") == symbol or q.get("yf_symbol") == symbol or q.get("name") == symbol):
            return q
    return None


def review_portfolio_risk(market: dict[str, Any]) -> list[dict[str, Any]]:
    """Returnerer risikoflag for eksisterende positioner uden at tvinge salg."""
    flags: list[dict[str, Any]] = []
    for p in _open_positions(market):
        pnl_pct = p.get("pnl_pct")
        if pnl_pct is None:
            open_price = _to_float(p.get("open_price") or p.get("avg_price") or p.get("purchase_price"), 0.0)
            current = _to_float(p.get("current_price") or p.get("price"), 0.0)
            pnl_pct = ((current / open_price) - 1) * 100 if open_price else None

        if pnl_pct is None:
            continue

        if pnl_pct <= REVIEW_LOSS_PCT:
            flags.append({
                "severity": "high",
                "symbol": p.get("symbol") or p.get("name"),
                "pnl_pct": round(float(pnl_pct), 2),
                "message": "Positionen er faldet markant. Genbesøg thesis, nyheder og risiko — sælg kun hvis thesis er brudt.",
            })
        elif pnl_pct >= TAKE_PROFIT_REVIEW_PCT:
            flags.append({
                "severity": "medium",
                "symbol": p.get("symbol") or p.get("name"),
                "pnl_pct": round(float(pnl_pct), 2),
                "message": "Positionen er steget markant. Overvej delvis gevinsthjemtagning eller trailing stop i planen.",
            })
    return flags


def normalize_decision(decision: dict[str, Any], market: dict[str, Any]) -> dict[str, Any]:
    """Normaliserer en AI-beslutning til et sikkert analyse-/dashboard-format."""
    now = datetime.now(timezone.utc).isoformat()
    decision = dict(decision or {})

    action = str(decision.get("action", "HOLD")).upper()
    if action not in VALID_ACTIONS:
        action = "HOLD"

    raw_uic = decision.get("uic")
    try:
        uic = int(raw_uic) if raw_uic not in (None, "", "null") else None
    except (TypeError, ValueError):
        uic = None

    symbol = decision.get("symbol")
    known = KNOWN_BY_UIC.get(uic) if uic is not None else None
    if not known and symbol:
        known = KNOWN_BY_SYMBOL.get(symbol)

    quote = _find_quote(market, symbol=symbol, uic=uic)
    price = _to_float(decision.get("price"), 0.0) or _to_float((quote or {}).get("price"), 0.0)

    amount = int(_to_float(decision.get("amount"), 0))
    portfolio_value = _portfolio_value(market)
    max_value = portfolio_value * MAX_SINGLE_IDEA_WEIGHT if portfolio_value else 0.0
    estimated_value = amount * price if amount and price else 0.0

    warnings: list[str] = []
    approved_for_log = True

    if action in {"BUY", "SELL"} and not known:
        approved_for_log = False
        warnings.append("Ukendt eller ikke-handlebar UIC/symbol i watchlist.")

    if action == "BUY":
        if price <= 0:
            warnings.append("Mangler valid prisdata; behold som analyseidé, ikke konkret ordre.")
        if estimated_value and max_value and estimated_value > max_value:
            warnings.append(f"Forslaget overstiger {MAX_SINGLE_IDEA_WEIGHT:.0%} af porteføljen som enkeltidé.")
        if amount <= 0:
            warnings.append("Mangler antal; behandles som kvalitativ købsidé.")
    elif action == "SELL" and amount <= 0:
        warnings.append("Mangler antal; behandles som kvalitativ salgs-/reduktionsidé.")

    risk_flags = review_portfolio_risk(market)
    if risk_flags:
        warnings.append("Porteføljen har positioner der kræver manuel risikogennemgang.")

    reasoning = decision.get("reasoning")
    if not isinstance(reasoning, dict):
        reasoning = {
            "verdict": action,
            "summary": decision.get("reason", "Ingen begrundelse angivet."),
        }

    if warnings:
        reasoning["risk_notes"] = warnings

    return {
        "timestamp": now,
        "action": action if approved_for_log else "HOLD",
        "symbol": (known or {}).get("symbol") or symbol,
        "name": (known or {}).get("name") or decision.get("name") or symbol,
        "uic": (known or {}).get("uic") if known else uic,
        "amount": amount,
        "price": price,
        "estimated_value": estimated_value or None,
        "reason": decision.get("reason") or reasoning.get("summary") or "",
        "reasoning": reasoning,
        "risk_flags": risk_flags,
        "approved_for_log": approved_for_log,
        "execution": "none",
    }
