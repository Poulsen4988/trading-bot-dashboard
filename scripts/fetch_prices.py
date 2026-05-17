"""
Henter dagens priser + tekniske indikatorer for alle C25-aktier via yfinance.
Gemmer til prices/latest.json.

Tekniske indikatorer (RSI, SMA50/200, MACD, ATR, Bollinger, Stochastic)
udregnes her fra 1 års historik — GitHub Actions har netværk, så det er
eneste sandhed. screener.py læser dem færdige.

Køres af GitHub Actions før bot-kørslerne.
"""
import json
import math
import os
import sys
from datetime import datetime, timezone

import yfinance as yf

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPT_DIR)

from watchlist import C25

os.makedirs(os.path.join(SCRIPT_DIR, "prices"), exist_ok=True)


# --- Indikator-beregninger -------------------------------------------------

def _sma(series, n):
    return sum(series[-n:]) / n if len(series) >= n else None


def _ema(series, n):
    if len(series) < n:
        return None
    k = 2 / (n + 1)
    val = sum(series[:n]) / n
    for price in series[n:]:
        val = price * k + val * (1 - k)
    return val


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


def _macd(closes, fast=12, slow=26):
    e_fast = _ema(closes, fast)
    e_slow = _ema(closes, slow)
    if e_fast is None or e_slow is None:
        return None
    return round(e_fast - e_slow, 4)


def _bollinger(closes, n=20, k=2):
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
        trs.append(max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        ))
    return round(sum(trs[-period:]) / period, 4)


def _stochastic(highs, lows, closes, k_period=14):
    if len(closes) < k_period:
        return None
    recent_high = max(highs[-k_period:])
    recent_low = min(lows[-k_period:])
    if recent_high == recent_low:
        return 50.0
    return round((closes[-1] - recent_low) / (recent_high - recent_low) * 100, 1)


def compute_technical(closes, highs, lows, vols, pct_high, pct_low):
    """Fuldt indikatorsæt fra historik — samme form som screener forventer."""
    if len(closes) < 20:
        return None

    price = closes[-1]
    rsi = _rsi(closes)
    macd_line = _macd(closes)
    bb_upper, bb_mid, bb_lower = _bollinger(closes)
    atr = _atr(highs, lows, closes)
    stoch = _stochastic(highs, lows, closes)
    sma50 = _sma(closes, 50)
    sma200 = _sma(closes, 200)

    avg_vol_20 = sum(vols[-20:]) / 20 if len(vols) >= 20 else None
    vol_ratio = round(vols[-1] / avg_vol_20, 2) if avg_vol_20 and avg_vol_20 > 0 else None

    mom5 = round((price - closes[-6]) / closes[-6] * 100, 2) if len(closes) >= 6 else None
    mom20 = round((price - closes[-21]) / closes[-21] * 100, 2) if len(closes) >= 21 else None

    bb_position = None
    if bb_upper and bb_lower and bb_upper != bb_lower:
        bb_position = round((price - bb_lower) / (bb_upper - bb_lower) * 100, 1)

    sma50_vs = round((price - sma50) / sma50 * 100, 2) if sma50 else None
    sma200_vs = round((price - sma200) / sma200 * 100, 2) if sma200 else None

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
        "stoch": stoch,
        "stoch_proxy": stoch,
        "sma50": round(sma50, 2) if sma50 else None,
        "sma200": round(sma200, 2) if sma200 else None,
        "sma50_vs_price": sma50_vs,
        "sma200_vs_price": sma200_vs,
        "volume_ratio": vol_ratio,
        "momentum_5d": mom5,
        "momentum_20d": mom20,
        "momentum_divergence": round((mom5 or 0) - (mom20 or 0), 2),
        "pct_from_52w_high": pct_high,
        "pct_from_52w_low": pct_low,
    }


# --- Hovedløb --------------------------------------------------------------

tickers = [s["yf"] for s in C25]
print(f"[fetch_prices] Henter {len(tickers)} aktier (1 års historik)...")

hist = yf.download(tickers, period="1y", interval="1d", auto_adjust=True,
                   progress=False, group_by="ticker")

stocks = {}
for s in C25:
    sym = s["yf"]
    try:
        t = yf.Ticker(sym)
        info = t.info

        df = hist[sym] if sym in getattr(hist.columns, "levels", [[]])[0] else hist
        closes = df["Close"].dropna().tolist()
        highs = df["High"].dropna().tolist()
        lows = df["Low"].dropna().tolist()
        vols = df["Volume"].dropna().tolist()

        price = float(closes[-1]) if closes else None
        pct_1d = round((closes[-1] / closes[-2] - 1) * 100, 2) if len(closes) >= 2 else None
        pct_5d = round((closes[-1] / closes[-6] - 1) * 100, 2) if len(closes) >= 6 else None
        pct_20d = round((closes[-1] / closes[-21] - 1) * 100, 2) if len(closes) >= 21 else None

        hi52 = info.get("fiftyTwoWeekHigh")
        lo52 = info.get("fiftyTwoWeekLow")
        avg_vol = info.get("averageVolume")
        vol = info.get("regularMarketVolume")
        pct_high = round((price / hi52 - 1) * 100, 2) if price and hi52 else None
        pct_low = round((price / lo52 - 1) * 100, 2) if price and lo52 else None

        # Udbytteafkast — eneste sandhed. yfinance returnerer dividendYield
        # som procent-tal direkte (0.44 = 0.44%, 5.31 = 5.31%).
        raw_dy = info.get("dividendYield")
        if raw_dy is None or raw_dy < 0 or raw_dy > 30:
            div_yield = None
        else:
            div_yield = round(raw_dy, 2)

        technical = compute_technical(closes, highs, lows, vols, pct_high, pct_low)

        stocks[sym] = {
            "price": round(price, 2) if price is not None else None,
            "pct_1d": pct_1d,
            "pct_5d": pct_5d,
            "pct_20d": pct_20d,
            "pe_forward": info.get("forwardPE"),
            "pe_trailing": info.get("trailingPE"),
            "div_yield": div_yield,
            "volume_ratio": round(vol / avg_vol, 2) if vol and avg_vol else (technical or {}).get("volume_ratio"),
            "52w_high": hi52,
            "52w_low": lo52,
            "pct_from_52w_high": pct_high,
            "pct_from_52w_low": pct_low,
            "revenue_growth": info.get("revenueGrowth"),
            "earnings_growth": info.get("earningsGrowth"),
            "market_cap": info.get("marketCap"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "technical": technical,
        }
        method = (technical or {}).get("method", "ingen")
        print(f"[fetch_prices]   {s['name']}: {price} (indikatorer: {method})")
    except Exception as e:
        stocks[sym] = {"error": str(e)}
        print(f"[fetch_prices]   FEJL {s['name']}: {e}")

now = datetime.now(timezone.utc)
result = {
    "date": now.date().isoformat(),
    "fetched_at": now.isoformat(),
    "stocks": stocks,
}
out = os.path.join(SCRIPT_DIR, "prices", "latest.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

ok = sum(1 for v in stocks.values() if "error" not in v and v.get("price"))
print(f"[fetch_prices] Faerdig: {ok}/{len(tickers)} aktier hentet -> {out}")
