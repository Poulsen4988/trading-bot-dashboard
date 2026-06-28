"""
Fetches today's prices + technical indicators for all S&P 500 stocks via yfinance.
Builds us/prices/latest.json and us/prices/benchmarks.json and PUSHES them to GitHub
(no GitHub Action commits these for the US bot).

Technical indicators (RSI, SMA50/200, MACD, ATR, Bollinger, Stochastic) are computed
here from ~1 year of history. screener.py reads them ready-made.

~503 tickers are downloaded in CHUNKS of ~100 via yf.download(..., group_by='ticker',
threads=True) with retry per chunk, then merged.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import math
import time
from datetime import datetime, timezone

import yfinance as yf

import watchlist
import github_store

# github_store reads PAT/REPO from env (DASHBOARD_REPO, GITHUB_TOKEN/DASHBOARD_PAT).
# Default only the repo; the token MUST come from the runner env (never hardcode it).
os.environ.setdefault("DASHBOARD_REPO", "poulsen4988/trading-bot-dashboard")

CHUNK_SIZE = 100


def download_retry(tickers, *, retries=3, backoff=3, **kw):
    """yf.download with retry on transient errors/empty responses. May return an
    empty DataFrame after the last attempt — the caller decides if that's fatal."""
    last = None
    for attempt in range(retries):
        try:
            df = yf.download(tickers, **kw)
            if df is not None and not df.empty:
                return df
            last = "empty response"
        except Exception as e:
            last = e
        if attempt < retries - 1:
            time.sleep(backoff * (attempt + 1))
    print(f"[fetch_prices] WARNING: download failed after {retries} attempts: {last}", file=sys.stderr)
    import pandas as pd
    return pd.DataFrame()


def download_chunked(tickers, **kw):
    """Download a large ticker list in chunks of CHUNK_SIZE; return {sym: DataFrame}.
    Each chunk uses group_by='ticker' so columns are MultiIndex (sym, field)."""
    out = {}
    for i in range(0, len(tickers), CHUNK_SIZE):
        chunk = tickers[i:i + CHUNK_SIZE]
        n = i // CHUNK_SIZE + 1
        print(f"[fetch_prices] chunk {n}: {len(chunk)} tickers...")
        hist = download_retry(chunk, group_by="ticker", threads=True, **kw)
        if hist is None or hist.empty:
            print(f"[fetch_prices]   chunk {n}: empty", file=sys.stderr)
            continue
        has_multi = hasattr(hist.columns, "get_level_values")
        level0 = set(hist.columns.get_level_values(0)) if has_multi else set()
        for sym in chunk:
            try:
                if has_multi and sym in level0:
                    out[sym] = hist[sym]
                elif len(chunk) == 1:
                    out[sym] = hist
            except Exception:
                pass
    return out


# --- Indicator computations ------------------------------------------------

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
    """Full indicator set from history — same shape the screener expects."""
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


# --- Main loop -------------------------------------------------------------

tickers = [s["yf"] for s in watchlist.SP500]
print(f"[fetch_prices] Fetching {len(tickers)} stocks (1y history, chunks of {CHUNK_SIZE})...")

hist_by_sym = download_chunked(tickers, period="1y", interval="1d",
                               auto_adjust=True, progress=False)
if not hist_by_sym:
    print("[fetch_prices] ERROR: no price data downloaded — keeping previous latest.json.", file=sys.stderr)
    sys.exit(1)

stocks = {}
for s in watchlist.SP500:
    sym = s["yf"]
    try:
        df = hist_by_sym.get(sym)
        if df is None:
            stocks[sym] = {"error": "no history"}
            print(f"[fetch_prices]   MISSING {s['name']}: no history")
            continue

        closes = df["Close"].dropna().tolist()
        highs = df["High"].dropna().tolist()
        lows = df["Low"].dropna().tolist()
        vols = df["Volume"].dropna().tolist()

        price = float(closes[-1]) if closes else None
        pct_1d = round((closes[-1] / closes[-2] - 1) * 100, 2) if len(closes) >= 2 else None
        pct_5d = round((closes[-1] / closes[-6] - 1) * 100, 2) if len(closes) >= 6 else None
        pct_20d = round((closes[-1] / closes[-21] - 1) * 100, 2) if len(closes) >= 21 else None

        # .info is per-ticker; fail-soft so one bad symbol can't sink the run.
        info = {}
        try:
            info = yf.Ticker(sym).info or {}
        except Exception:
            info = {}

        hi52 = info.get("fiftyTwoWeekHigh")
        lo52 = info.get("fiftyTwoWeekLow")
        avg_vol = info.get("averageVolume")
        vol = info.get("regularMarketVolume")
        pct_high = round((price / hi52 - 1) * 100, 2) if price and hi52 else None
        pct_low = round((price / lo52 - 1) * 100, 2) if price and lo52 else None

        # Dividend yield — yfinance returns it as a percentage number directly
        # (0.44 = 0.44%, 5.31 = 5.31%).
        raw_dy = info.get("dividendYield")
        if raw_dy is None or raw_dy < 0 or raw_dy > 30:
            div_yield = None
        else:
            div_yield = round(raw_dy, 2)

        technical = compute_technical(closes, highs, lows, vols, pct_high, pct_low)

        # Next earnings date — yfinance returns dict, DataFrame or None
        next_earnings = None
        try:
            cal = yf.Ticker(sym).calendar
            if isinstance(cal, dict):
                ed = cal.get("Earnings Date")
                if isinstance(ed, list) and ed:
                    next_earnings = str(ed[0])[:10]
                elif ed:
                    next_earnings = str(ed)[:10]
            elif cal is not None and hasattr(cal, "index") and "Earnings Date" in getattr(cal, "index", []):
                next_earnings = str(cal.loc["Earnings Date"].iloc[0])[:10]
        except Exception:
            next_earnings = None

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
            "sector": info.get("sector") or watchlist.YF_TO_SECTOR.get(sym),
            "industry": info.get("industry"),
            "next_earnings_date": next_earnings,
            "technical": technical,
        }
        method = (technical or {}).get("method", "none")
        print(f"[fetch_prices]   {s['name']}: {price} (indicators: {method})")
    except Exception as e:
        stocks[sym] = {"error": str(e)}
        print(f"[fetch_prices]   ERROR {s['name']}: {e}")

now = datetime.now(timezone.utc)
ok = sum(1 for v in stocks.values() if "error" not in v and v.get("price"))

# Fail-loud: do NOT overwrite a good remote latest.json with an empty fetch.
if ok == 0:
    print(f"[fetch_prices] ERROR: 0/{len(tickers)} stocks fetched — keeping previous latest.json.", file=sys.stderr)
    sys.exit(1)

result = {
    "date": now.date().isoformat(),
    "fetched_at": now.isoformat(),
    "stocks": stocks,
}
github_store.put_json("us/prices/latest.json", result,
                      f"US bot: prices latest.json ({ok}/{len(tickers)} ok)")
print(f"[fetch_prices] Done: {ok}/{len(tickers)} stocks fetched -> us/prices/latest.json")


# --- Benchmark fetch -------------------------------------------------------
# ^GSPC = S&P 500 index; ^NDX = Nasdaq-100 (secondary).

BENCHMARK_TICKERS = ["^GSPC", "^NDX"]
BENCHMARK_LABELS = {
    "^GSPC": "S&P 500",
    "^NDX": "Nasdaq-100",
}

print(f"[fetch_prices] Fetching benchmarks: {', '.join(BENCHMARK_TICKERS)} (1y history)...")
bench_hist = download_retry(BENCHMARK_TICKERS, period="1y", interval="1d", auto_adjust=True,
                            progress=False, group_by="ticker", threads=True)

benchmarks = {}
for bsym in BENCHMARK_TICKERS:
    try:
        if hasattr(bench_hist.columns, "levels") and bsym in bench_hist.columns.get_level_values(0):
            df = bench_hist[bsym]
        else:
            df = bench_hist
        closes = df["Close"].dropna()
        if closes.empty:
            benchmarks[bsym] = {"error": "no data"}
            print(f"[fetch_prices]   {bsym}: NO DATA")
            continue

        history = [
            {"date": idx.date().isoformat(), "close": round(float(c), 4)}
            for idx, c in closes.items()
        ]
        price = float(closes.iloc[-1])
        pct_1d = round((closes.iloc[-1] / closes.iloc[-2] - 1) * 100, 2) if len(closes) >= 2 else None
        pct_5d = round((closes.iloc[-1] / closes.iloc[-6] - 1) * 100, 2) if len(closes) >= 6 else None
        pct_20d = round((closes.iloc[-1] / closes.iloc[-21] - 1) * 100, 2) if len(closes) >= 21 else None

        benchmarks[bsym] = {
            "label": BENCHMARK_LABELS.get(bsym, bsym),
            "price": round(price, 4),
            "pct_1d": pct_1d,
            "pct_5d": pct_5d,
            "pct_20d": pct_20d,
            "history": history,
        }
        print(f"[fetch_prices]   {bsym}: {price:.2f} ({len(history)} days)")
    except Exception as e:
        benchmarks[bsym] = {"error": str(e)}
        print(f"[fetch_prices]   ERROR {bsym}: {e}")

github_store.put_json("us/prices/benchmarks.json", {
    "date": now.date().isoformat(),
    "fetched_at": now.isoformat(),
    "benchmarks": benchmarks,
}, "US bot: prices benchmarks.json")
print("[fetch_prices] Benchmarks saved -> us/prices/benchmarks.json")
