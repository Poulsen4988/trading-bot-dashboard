#!/usr/bin/env python3
"""
C25 Screener — OMX Copenhagen / C25 paper-trading dashboard.
Paper trading only. No real orders. No Saxo. No hardcoded secrets.

Flow:
  1. Try scripts/fetch_prices.py  (may be blocked by sandbox — OK)
  2. Load prices/latest.json (already fresh from GitHub Action at 08:30)
  3. Try to fetch 250-day history from yfinance for full technical indicators
  4. Fall back to snapshot-based proxy indicators if network unavailable
  5. Score all C25 stocks on a multi-factor model
  6. Select 3-5 most analytically interesting names
  7. Save to screening/YYYY-MM-DD.json
"""

import json
import math
import os
import subprocess
import sys
from datetime import date, datetime

from watchlist import STOCKS

PRICES_FILE = "prices/latest.json"
SCREENING_DIR = "screening"

# Sector forward-PE norms used for valuation scoring
SECTOR_PE_NORMS = {
    "Healthcare":        25,
    "Industrials":       18,
    "Consumer Cyclical": 20,
    "Consumer Defensive":17,
    "Financial Services":12,
    "Technology":        22,
    "Utilities":         20,
    "Basic Materials":   16,
    "Energy":            15,
}


# ---------------------------------------------------------------------------
# Data fetching helpers
# ---------------------------------------------------------------------------

def try_fetch_prices():
    """Run scripts/fetch_prices.py; sandbox network block is expected and harmless."""
    try:
        res = subprocess.run(
            [sys.executable, "scripts/fetch_prices.py"],
            capture_output=True, text=True, timeout=120,
        )
        if res.returncode == 0:
            print(f"[fetch_prices] OK — {res.stdout.strip()}")
            return True
        else:
            print(f"[fetch_prices] non-zero exit (network likely blocked) — using fallback latest.json")
    except Exception as e:
        print(f"[fetch_prices] blocked ({e}) — using fallback latest.json")
    return False


def load_prices():
    with open(PRICES_FILE) as f:
        return json.load(f)


def try_fetch_history(symbols, period="250d"):
    """Attempt to pull full price history via yfinance for indicator calculation."""
    try:
        import yfinance as yf
        tickers = yf.download(
            " ".join(symbols), period=period, auto_adjust=True, progress=False, group_by="ticker"
        )
        print(f"[yfinance history] fetched {period} history for {len(symbols)} symbols")
        return tickers
    except Exception as e:
        print(f"[yfinance history] unavailable ({e}) — using snapshot proxies")
        return None


# ---------------------------------------------------------------------------
# Technical indicator computation
# ---------------------------------------------------------------------------

def _sma(series, n):
    if len(series) < n:
        return None
    return sum(series[-n:]) / n


def _rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(d, 0) for d in deltas[-period:]]
    losses = [max(-d, 0) for d in deltas[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 1)


def _macd(closes, fast=12, slow=26, signal=9):
    """Returns (macd_line, signal_line, histogram) or (None, None, None)."""
    def ema(series, n):
        if len(series) < n:
            return None
        k = 2 / (n + 1)
        val = sum(series[:n]) / n
        for price in series[n:]:
            val = price * k + val * (1 - k)
        return val

    e_fast = ema(closes, fast)
    e_slow = ema(closes, slow)
    if e_fast is None or e_slow is None:
        return None, None, None
    macd_line = e_fast - e_slow
    # signal line needs at least `signal` MACD values — approximate
    return round(macd_line, 4), None, None


def _bollinger(closes, n=20, k=2):
    """Returns (upper, mid, lower) or (None, None, None)."""
    if len(closes) < n:
        return None, None, None
    window = closes[-n:]
    mid = sum(window) / n
    std = math.sqrt(sum((p - mid) ** 2 for p in window) / n)
    return round(mid + k * std, 4), round(mid, 4), round(mid - k * std, 4)


def _atr(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return None
    trs = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    return round(sum(trs[-period:]) / period, 4)


def _stochastic(highs, lows, closes, k_period=14):
    if len(closes) < k_period:
        return None
    recent_high = max(highs[-k_period:])
    recent_low = min(lows[-k_period:])
    if recent_high == recent_low:
        return 50.0
    k = (closes[-1] - recent_low) / (recent_high - recent_low) * 100
    return round(k, 1)


def compute_indicators_from_history(sym, hist_data, snapshot):
    """Full indicators from yfinance historical data."""
    try:
        if hasattr(hist_data, "columns") and hasattr(hist_data.columns, "levels"):
            # Multi-ticker download
            if sym not in hist_data.columns.get_level_values(0):
                return compute_indicators_from_snapshot(snapshot)
            closes = hist_data[sym]["Close"].dropna().tolist()
            highs  = hist_data[sym]["High"].dropna().tolist()
            lows   = hist_data[sym]["Low"].dropna().tolist()
            vols   = hist_data[sym]["Volume"].dropna().tolist()
        else:
            closes = hist_data["Close"].dropna().tolist()
            highs  = hist_data["High"].dropna().tolist()
            lows   = hist_data["Low"].dropna().tolist()
            vols   = hist_data["Volume"].dropna().tolist()
    except Exception:
        return compute_indicators_from_snapshot(snapshot)

    if len(closes) < 20:
        return compute_indicators_from_snapshot(snapshot)

    rsi = _rsi(closes)
    macd_line, _, _ = _macd(closes)
    bb_upper, bb_mid, bb_lower = _bollinger(closes)
    atr = _atr(highs, lows, closes)
    stoch = _stochastic(highs, lows, closes)
    sma50 = _sma(closes, 50)
    sma200 = _sma(closes, 200)

    price = closes[-1]
    avg_vol_20 = sum(vols[-20:]) / 20 if len(vols) >= 20 else None
    vol_ratio = round(vols[-1] / avg_vol_20, 2) if avg_vol_20 and avg_vol_20 > 0 else snapshot.get("volume_ratio")

    mom5  = round((price - closes[-6])  / closes[-6]  * 100, 2) if len(closes) >= 6  else snapshot.get("pct_5d")
    mom20 = round((price - closes[-21]) / closes[-21] * 100, 2) if len(closes) >= 21 else snapshot.get("pct_20d")

    bb_position = None
    if bb_upper and bb_lower and bb_upper != bb_lower:
        bb_position = round((price - bb_lower) / (bb_upper - bb_lower) * 100, 1)

    sma50_vs_price = round((price - sma50) / sma50 * 100, 2) if sma50 else None
    sma200_vs_price = round((price - sma200) / sma200 * 100, 2) if sma200 else None

    return {
        "method": "yfinance_historical",
        "rsi": rsi,
        "rsi_proxy": rsi,
        "macd_line": macd_line,
        "bb_upper": bb_upper,
        "bb_mid": bb_mid,
        "bb_lower": bb_lower,
        "bb_position": bb_position,
        "atr": atr,
        "stoch_proxy": stoch,
        "stoch": stoch,
        "sma50": round(sma50, 2) if sma50 else None,
        "sma200": round(sma200, 2) if sma200 else None,
        "sma50_vs_price": sma50_vs_price,
        "sma200_vs_price": sma200_vs_price,
        "volume_ratio": vol_ratio,
        "momentum_5d": mom5,
        "momentum_20d": mom20,
        "momentum_divergence": round((mom5 or 0) - (mom20 or 0), 2),
        "pct_from_52w_high": snapshot.get("pct_from_52w_high"),
        "pct_from_52w_low": snapshot.get("pct_from_52w_low"),
    }


def compute_indicators_from_snapshot(data):
    """Proxy indicators derived from the daily snapshot fields in latest.json."""
    pct_1d  = data.get("pct_1d", 0) or 0
    pct_5d  = data.get("pct_5d", 0) or 0
    pct_20d = data.get("pct_20d", 0) or 0
    vol_ratio = data.get("volume_ratio") or 1.0
    price = data.get("price", 0)
    w52_high = data.get("52w_high")
    w52_low  = data.get("52w_low")
    pct_high = data.get("pct_from_52w_high")
    pct_low  = data.get("pct_from_52w_low")

    # RSI proxy: map 5-day momentum linearly (−10% ≈ RSI 20, +10% ≈ RSI 80)
    rsi_proxy = max(0, min(100, 50 + pct_5d * 3))

    # Stochastic proxy: position within 52-week range
    if w52_high and w52_low and w52_high != w52_low:
        stoch_proxy = max(0, min(100, (price - w52_low) / (w52_high - w52_low) * 100))
    else:
        stoch_proxy = 50.0

    # Bollinger proxy: same as stochastic (annual range acts as wide band)
    bb_position = stoch_proxy

    # MACD proxy: 5d momentum minus ¼ of 20d momentum (short vs long EMA delta)
    macd_proxy = pct_5d - pct_20d / 4

    return {
        "method": "snapshot_proxy",
        "rsi": None,
        "rsi_proxy": round(rsi_proxy, 1),
        "macd_line": round(macd_proxy, 3),
        "bb_upper": None, "bb_mid": None, "bb_lower": None,
        "bb_position": round(bb_position, 1),
        "atr": None,
        "stoch": None,
        "stoch_proxy": round(stoch_proxy, 1),
        "sma50": None, "sma200": None,
        "sma50_vs_price": None, "sma200_vs_price": None,
        "volume_ratio": vol_ratio,
        "momentum_5d": pct_5d,
        "momentum_20d": pct_20d,
        "momentum_divergence": round(pct_5d - pct_20d, 2),
        "pct_from_52w_high": pct_high,
        "pct_from_52w_low": pct_low,
    }


# ---------------------------------------------------------------------------
# Scoring model
# ---------------------------------------------------------------------------

def score_stock(sym, data, ind):
    """
    Multi-factor interestingness score (0–100).
    Higher = more analytically interesting today.
    """
    score = 0.0
    signals = []

    vol_ratio   = ind["volume_ratio"] or 1.0
    rsi         = ind["rsi_proxy"]
    stoch       = ind["stoch_proxy"]
    bb_pos      = ind["bb_position"]
    mom5        = ind["momentum_5d"] or 0
    mom20       = ind["momentum_20d"] or 0
    mom_div     = ind["momentum_divergence"] or 0
    pct_high    = ind["pct_from_52w_high"]
    pct_low     = ind["pct_from_52w_low"]
    pe_fwd      = data.get("pe_forward")
    eg          = data.get("earnings_growth")
    rg          = data.get("revenue_growth")
    sector      = data.get("sector", "")
    raw_dy = data.get("div_yield") or 0
    # Sanitize: yfinance sometimes returns dividend amount (not yield); cap at 30%
    if raw_dy and raw_dy <= 1.0:
        div_yield = raw_dy * 100   # decimal → percent
    elif raw_dy and raw_dy <= 30.0:
        div_yield = raw_dy         # already in percent
    else:
        div_yield = 0              # bogus value (e.g. annual dividend in currency)

    # 1. Volume anomaly — max 30 pts
    if vol_ratio >= 2.5:
        score += 30
        signals.append(f"VOLUME SPIKE: {vol_ratio:.2f}x avg — extreme institutional activity")
    elif vol_ratio >= 1.5:
        score += 20
        signals.append(f"VOLUME ELEVATED: {vol_ratio:.2f}x avg — above-normal interest")
    elif vol_ratio >= 1.0:
        score += 12
        signals.append(f"VOLUME NORMAL-HIGH: {vol_ratio:.2f}x avg")
    else:
        score += max(0, vol_ratio * 8)

    # 2. Extreme 52-week position — max 25 pts
    if pct_low is not None and pct_low <= 3:
        score += 25
        signals.append(f"AT 52W LOW: +{pct_low:.1f}% above annual floor — breakdown or reversal imminent")
    elif pct_low is not None and pct_low <= 10:
        score += 20
        signals.append(f"NEAR 52W LOW: +{pct_low:.1f}% above annual support — critical level")
    elif pct_high is not None and pct_high <= -45:
        score += 18
        signals.append(f"DEEP DRAWDOWN: {pct_high:.1f}% from 52w high — severe compression, mean-reversion potential")
    elif pct_high is not None and pct_high <= -30:
        score += 12
        signals.append(f"SIGNIFICANT DRAWDOWN: {pct_high:.1f}% from 52w high")
    elif pct_high is not None and pct_high >= -5:
        score += 10
        signals.append(f"NEAR 52W HIGH: {pct_high:.1f}% — breakout territory")

    # 3. Momentum — max 20 pts
    if abs(mom5) >= 8:
        score += 20
        tag = "SELLOFF" if mom5 < 0 else "SURGE"
        signals.append(f"MOMENTUM {tag}: {mom5:+.1f}% in 5 days — sharp directional move")
    elif abs(mom5) >= 5:
        score += 14
        tag = "SELLING" if mom5 < 0 else "BUYING"
        signals.append(f"MOMENTUM: {mom5:+.1f}% in 5 days — continued {tag} pressure")
    elif abs(mom5) >= 2:
        score += 7
        signals.append(f"MOMENTUM: {mom5:+.1f}% in 5 days")

    # Momentum divergence (5d vs 20d) — reversal signal
    if abs(mom_div) >= 15:
        score += 7
        signals.append(f"MOMENTUM DIVERGENCE: 5d/20d gap {mom_div:+.1f}pp — strong trend change signal")
    elif abs(mom_div) >= 8:
        score += 4
        signals.append(f"MOMENTUM DIVERGENCE: 5d/20d gap {mom_div:+.1f}pp — emerging trend shift")

    # 4. RSI / Stochastic extremes — max 12 pts
    if rsi <= 25 and stoch <= 15:
        score += 12
        signals.append(f"DEEPLY OVERSOLD: RSI proxy {rsi:.0f}, Stoch proxy {stoch:.0f} — bounce candidate")
    elif stoch <= 15:
        score += 12
        signals.append(f"STOCHASTIC OVERSOLD: Stoch proxy {stoch:.0f} — price near annual support floor (RSI proxy {rsi:.0f})")
    elif rsi <= 25:
        score += 12
        signals.append(f"RSI OVERSOLD: RSI proxy {rsi:.0f}, Stoch proxy {stoch:.0f} — momentum exhaustion signal")
    elif rsi <= 35 or stoch <= 25:
        score += 8
        if stoch <= 25 and rsi > 50:
            signals.append(f"STOCHASTIC LOW: Stoch proxy {stoch:.0f} — lower range of annual band; RSI proxy {rsi:.0f} (momentum not yet oversold)")
        else:
            signals.append(f"OVERSOLD: RSI proxy {rsi:.0f}, Stoch proxy {stoch:.0f} — watch for reversal")
    elif rsi >= 75 or stoch >= 85:
        score += 5
        signals.append(f"OVERBOUGHT: RSI proxy {rsi:.0f}, Stoch proxy {stoch:.0f} — stretched, potential pullback")

    # 5. Valuation — max 15 pts
    norm_pe = SECTOR_PE_NORMS.get(sector, 18)
    if pe_fwd and pe_fwd > 0:
        discount = (norm_pe - pe_fwd) / norm_pe
        if discount >= 0.40:
            score += 15
            signals.append(f"DEEP VALUE: Fwd PE {pe_fwd:.1f}x vs sector norm {norm_pe}x — {discount*100:.0f}% discount")
        elif discount >= 0.25:
            score += 10
            signals.append(f"UNDERVALUED: Fwd PE {pe_fwd:.1f}x vs sector norm {norm_pe}x — {discount*100:.0f}% discount")
        elif discount >= 0.10:
            score += 5
            signals.append(f"MODEST DISCOUNT: Fwd PE {pe_fwd:.1f}x vs sector norm {norm_pe}x")

    # 6. Earnings/revenue growth quality — max 10 pts
    if eg is not None:
        if eg >= 0.30:
            score += 10
            signals.append(f"STRONG EARNINGS GROWTH: +{eg*100:.0f}% YoY — fundamental tailwind")
        elif eg >= 0.10:
            score += 6
            signals.append(f"EARNINGS GROWTH: +{eg*100:.0f}% YoY")
        elif eg <= -0.40:
            score += 4
            signals.append(f"EARNINGS COLLAPSE: {eg*100:.0f}% YoY — risk/watch for stabilisation")
    if rg is not None and rg >= 0.30:
        score += 4
        signals.append(f"REVENUE GROWTH: +{rg*100:.0f}% YoY — top-line expansion")

    # 7. Dividend yield bonus for yield plays
    if div_yield and div_yield >= 5.0:
        score += 5
        signals.append(f"HIGH YIELD: {div_yield:.2f}% dividend provides downside cushion")
    elif div_yield and div_yield >= 3.0:
        score += 2

    return round(score, 1), signals


# ---------------------------------------------------------------------------
# Rationale builder
# ---------------------------------------------------------------------------

def build_rationale(sym, data, ind, signals):
    name = data.get("name", sym)
    price = data.get("price")
    mom5  = ind["momentum_5d"] or 0
    mom20 = ind["momentum_20d"] or 0
    vol   = ind["volume_ratio"] or 1.0
    pct_high = ind["pct_from_52w_high"]
    pct_low  = ind["pct_from_52w_low"]
    pe_fwd   = data.get("pe_forward")
    rsi      = ind["rsi_proxy"]
    stoch    = ind["stoch_proxy"]
    eg       = data.get("earnings_growth")
    sector   = data.get("sector", "")
    norm_pe  = SECTOR_PE_NORMS.get(sector, 18)
    method   = ind["method"]

    parts = []

    if vol >= 1.5:
        parts.append(f"volume running at {vol:.1f}x the daily average signals institutional-scale activity")

    if abs(mom5) >= 5:
        tag = "selloff" if mom5 < 0 else "rally"
        parts.append(f"a {abs(mom5):.1f}% five-day {tag} (20d: {mom20:+.1f}%) reveals strong directional pressure")

    if pct_low is not None and pct_low <= 10:
        parts.append(f"price sits just +{pct_low:.1f}% above the 52-week low ({data.get('52w_low')}) — a key decision zone")
    elif pct_high is not None and pct_high <= -40:
        parts.append(f"stock has shed {abs(pct_high):.0f}% from its 52-week high — potential deep value or extended downtrend")
    elif pct_high is not None and pct_high >= -5:
        parts.append(f"stock is pressing against its 52-week high at {pct_high:.1f}% — breakout watch")

    if pe_fwd and pe_fwd > 0:
        disc = (norm_pe - pe_fwd) / norm_pe * 100
        if abs(disc) >= 15:
            qual = f"{disc:.0f}% discount" if disc > 0 else f"{abs(disc):.0f}% premium"
            parts.append(f"forward PE {pe_fwd:.1f}x represents a {qual} to {sector} sector norm ({norm_pe}x)")

    if eg is not None and eg >= 0.25:
        parts.append(f"+{eg*100:.0f}% earnings growth underpins the fundamental case")
    elif eg is not None and eg <= -0.30:
        parts.append(f"{eg*100:.0f}% earnings decline warrants caution but may create a contrarian entry")

    if rsi <= 35:
        parts.append(f"RSI proxy ({rsi:.0f}) and stochastic ({stoch:.0f}) in oversold territory support a bounce thesis")

    if ind.get("sma50_vs_price") is not None:
        s50 = ind["sma50_vs_price"]
        parts.append(f"price is {s50:+.1f}% vs SMA50")

    if not parts:
        parts.append("combination of technical and fundamental signals make this worth a deeper look")

    proxy_note = "" if method == "yfinance_historical" else " (indicators computed from snapshot data)"
    return name + ": " + "; ".join(parts) + "." + proxy_note


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    today = date.today().isoformat()
    print(f"\n{'='*62}")
    print(f"  C25 SCREENER — {today}")
    print(f"{'='*62}\n")

    # Step 1: Try to refresh prices
    print("Step 1: Attempting to fetch fresh prices via scripts/fetch_prices.py ...")
    try_fetch_prices()

    # Step 2: Load snapshot data
    print(f"\nStep 2: Loading price snapshot from {PRICES_FILE} ...")
    try:
        price_data = load_prices()
    except FileNotFoundError:
        print(f"ERROR: {PRICES_FILE} not found and fetch failed. Cannot continue.")
        sys.exit(1)

    stocks_data = price_data.get("stocks", {})
    data_date   = price_data.get("date", "unknown")
    print(f"  Snapshot date  : {data_date}")
    print(f"  Stocks in file : {len(stocks_data)}")

    # Step 3: Try to fetch historical data for full technical indicators
    print("\nStep 3: Attempting yfinance historical download for technical indicators ...")
    valid_symbols = [s for s, _ in STOCKS if "price" in stocks_data.get(s, {})]
    hist = try_fetch_history(valid_symbols, period="250d")

    # Step 4: Compute indicators and score every stock
    print("\nStep 4: Computing indicators and scoring ...")
    scored = []
    valid_count = 0

    for sym, name in STOCKS:
        snap = stocks_data.get(sym, {})
        if "error" in snap or "price" not in snap:
            continue
        valid_count += 1

        if hist is not None:
            ind = compute_indicators_from_history(sym, hist, snap)
        else:
            ind = compute_indicators_from_snapshot(snap)

        score, signals = score_stock(sym, snap, ind)
        rationale = build_rationale(sym, snap, ind, signals)

        scored.append({
            "symbol":   sym,
            "name":     snap.get("name", name),
            "score":    score,
            "price":    snap.get("price"),
            "pct_1d":   snap.get("pct_1d"),
            "pct_5d":   snap.get("pct_5d"),
            "pct_20d":  snap.get("pct_20d"),
            "volume_ratio":       ind["volume_ratio"],
            "rsi_proxy":          ind["rsi_proxy"],
            "stoch_proxy":        ind["stoch_proxy"],
            "bb_position":        ind.get("bb_position"),
            "sma50_vs_price":     ind.get("sma50_vs_price"),
            "sma200_vs_price":    ind.get("sma200_vs_price"),
            "macd_line":          ind.get("macd_line"),
            "atr":                ind.get("atr"),
            "momentum_divergence":ind["momentum_divergence"],
            "pe_forward":         snap.get("pe_forward"),
            "pct_from_52w_high":  snap.get("pct_from_52w_high"),
            "pct_from_52w_low":   snap.get("pct_from_52w_low"),
            "sector":             snap.get("sector"),
            "earnings_growth":    snap.get("earnings_growth"),
            "revenue_growth":     snap.get("revenue_growth"),
            "div_yield":          snap.get("div_yield"),
            "indicator_method":   ind["method"],
            "signals":            signals,
            "rationale":          rationale,
        })

    print(f"  Scored {valid_count} stocks")

    # Step 5: Select top 3-5
    scored.sort(key=lambda x: x["score"], reverse=True)
    n_select = max(3, min(5, len(scored)))
    selected = scored[:n_select]

    print(f"\nStep 5: Top {n_select} selected:")
    for i, s in enumerate(selected, 1):
        print(f"  {i}. {s['symbol']:15s}  score={s['score']:5.1f}  {s['name']}")

    # Step 6: Save
    os.makedirs(SCREENING_DIR, exist_ok=True)
    out_path = f"{SCREENING_DIR}/{today}.json"

    output = {
        "date":             today,
        "screened_at":      datetime.utcnow().isoformat() + "Z",
        "price_data_date":  data_date,
        "universe_size":    valid_count,
        "indicator_method": selected[0]["indicator_method"] if selected else "unknown",
        "selected": [
            {
                "priority":           i + 1,
                "symbol":             s["symbol"],
                "name":               s["name"],
                "score":              s["score"],
                "price":              s["price"],
                "pct_1d":             s["pct_1d"],
                "pct_5d":             s["pct_5d"],
                "pct_20d":            s["pct_20d"],
                "volume_ratio":       s["volume_ratio"],
                "rsi_proxy":          s["rsi_proxy"],
                "stoch_proxy":        s["stoch_proxy"],
                "bb_position":        s["bb_position"],
                "sma50_vs_price":     s["sma50_vs_price"],
                "sma200_vs_price":    s["sma200_vs_price"],
                "macd_line":          s["macd_line"],
                "atr":                s["atr"],
                "momentum_divergence":s["momentum_divergence"],
                "pe_forward":         s["pe_forward"],
                "pct_from_52w_high":  s["pct_from_52w_high"],
                "pct_from_52w_low":   s["pct_from_52w_low"],
                "sector":             s["sector"],
                "earnings_growth":    s["earnings_growth"],
                "revenue_growth":     s["revenue_growth"],
                "div_yield":          s["div_yield"],
                "indicator_method":   s["indicator_method"],
                "screening_signals":  s["signals"],
                "screening_rationale":s["rationale"],
            }
            for i, s in enumerate(selected)
        ],
        "all_scores": [
            {"symbol": s["symbol"], "name": s["name"], "score": s["score"]}
            for s in scored
        ],
    }

    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nStep 6: Saved → {out_path}")

    return output, valid_count, selected


if __name__ == "__main__":
    result, valid_count, selected = main()

    print(f"\n{'='*62}")
    print("  SCREENING SUMMARY")
    print(f"{'='*62}")
    print(f"  Date            : {result['date']}")
    print(f"  Price data from : {result['price_data_date']}")
    print(f"  Indicator method: {result['indicator_method']}")
    print(f"  Stocks scored   : {valid_count}")
    print(f"\n  ── Selected stocks ──")
    for s in result["selected"]:
        print(f"\n  #{s['priority']}  {s['symbol']}  —  {s['name']}")
        print(f"       Score    : {s['score']}")
        price_str = f"{s['price']}" if s['price'] is not None else "N/A"
        print(f"       Price    : {price_str} DKK")
        p1 = s['pct_1d'] if s['pct_1d'] is not None else 0
        p5 = s['pct_5d'] if s['pct_5d'] is not None else 0
        print(f"       1d/5d   : {p1:+.2f}% / {p5:+.2f}%")
        print(f"       Vol ratio: {s['volume_ratio']}x")
        print(f"       RSI proxy: {s['rsi_proxy']}")
        for sig in s['screening_signals']:
            print(f"       • {sig}")
        print(f"       Rationale: {s['screening_rationale']}")
