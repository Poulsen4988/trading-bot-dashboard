import json
import os
from datetime import date, datetime

import yfinance as yf
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.trend import MACD, SMAIndicator
from ta.volatility import AverageTrueRange, BollingerBands

from watchlist import C25


def safe(v):
    if v is None:
        return None
    try:
        f = float(v)
        return None if f != f else round(f, 4)
    except Exception:
        return None


def build_stock(name, ticker):
    info = ticker.info
    hist = ticker.history(period="1y")
    if hist.empty or len(hist) < 30:
        return {"name": name, "error": "no data"}

    close = hist["Close"]
    high = hist["High"]
    low = hist["Low"]
    vol = hist["Volume"]
    price = float(close.iloc[-1])
    prev = float(close.iloc[-2])
    avg_vol = float(vol.mean())
    cur_vol = float(vol.iloc[-1])

    rsi = macd_val = macd_sig = macd_hist = None
    bb_upper = bb_lower = bb_pct = None
    sma50 = sma200 = atr = stoch_k = stoch_d = None

    if len(close) >= 14:
        rsi = safe(RSIIndicator(close, window=14).rsi().iloc[-1])
        stoch = StochasticOscillator(high, low, close, window=14, smooth_window=3)
        stoch_k = safe(stoch.stoch().iloc[-1])
        stoch_d = safe(stoch.stoch_signal().iloc[-1])
        atr = safe(AverageTrueRange(high, low, close, window=14).average_true_range().iloc[-1])

    if len(close) >= 26:
        m = MACD(close, window_slow=26, window_fast=12, window_sign=9)
        macd_val = safe(m.macd().iloc[-1])
        macd_sig = safe(m.macd_signal().iloc[-1])
        macd_hist = safe(m.macd_diff().iloc[-1])

    if len(close) >= 20:
        bb = BollingerBands(close, window=20, window_dev=2)
        bb_upper = safe(bb.bollinger_hband().iloc[-1])
        bb_lower = safe(bb.bollinger_lband().iloc[-1])
        bb_pct = safe(bb.bollinger_pband().iloc[-1])

    if len(close) >= 50:
        sma50 = safe(SMAIndicator(close, window=50).sma_indicator().iloc[-1])
    if len(close) >= 200:
        sma200 = safe(SMAIndicator(close, window=200).sma_indicator().iloc[-1])

    rsi_signal = "neutral"
    if rsi is not None:
        if rsi < 30:
            rsi_signal = "oversold"
        elif rsi > 70:
            rsi_signal = "overbought"

    macd_cross = "neutral"
    if macd_hist is not None:
        macd_cross = "bullish" if macd_hist > 0 else "bearish" if macd_hist < 0 else "neutral"

    trend = "unknown"
    if sma200 is not None:
        trend = "above_200ma" if price > sma200 else "below_200ma"

    pct_5d = safe((price - float(close.iloc[-6])) / float(close.iloc[-6]) * 100) if len(close) >= 6 else None
    pct_20d = safe((price - float(close.iloc[-21])) / float(close.iloc[-21]) * 100) if len(close) >= 21 else None
    hi52 = info.get("fiftyTwoWeekHigh")
    lo52 = info.get("fiftyTwoWeekLow")

    return {
        "name": name,
        "price": round(price, 4),
        "prev_close": round(prev, 4),
        "pct_1d": safe((price - prev) / prev * 100),
        "pct_5d": pct_5d,
        "pct_20d": pct_20d,
        "volume": int(cur_vol),
        "avg_volume": int(avg_vol),
        "volume_ratio": safe(cur_vol / avg_vol) if avg_vol else None,
        "pe_trailing": safe(info.get("trailingPE")),
        "pe_forward": safe(info.get("forwardPE")),
        "market_cap": info.get("marketCap"),
        "52w_high": safe(hi52),
        "52w_low": safe(lo52),
        "pct_from_52w_high": safe((price - hi52) / hi52 * 100) if hi52 else None,
        "pct_from_52w_low": safe((price - lo52) / lo52 * 100) if lo52 else None,
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "beta": safe(info.get("beta")),
        "div_yield": safe(info["dividendYield"] * 100) if info.get("dividendYield") else None,
        "revenue_growth": safe(info.get("revenueGrowth")),
        "earnings_growth": safe(info.get("earningsGrowth")),
        "technical": {
            "rsi": rsi,
            "rsi_signal": rsi_signal,
            "macd": macd_val,
            "macd_signal": macd_sig,
            "macd_hist": macd_hist,
            "macd_cross": macd_cross,
            "bb_upper": bb_upper,
            "bb_lower": bb_lower,
            "bb_pct": bb_pct,
            "sma50": sma50,
            "sma200": sma200,
            "trend": trend,
            "golden_cross": bool(sma50 is not None and sma200 is not None and sma50 > sma200),
            "death_cross": bool(sma50 is not None and sma200 is not None and sma50 < sma200),
            "atr": atr,
            "stoch_k": stoch_k,
            "stoch_d": stoch_d,
        },
        "source": "yfinance",
    }


def fetch_news(ticker, name):
    news_items = []
    try:
        for item in (ticker.news or [])[:5]:
            title = (item.get("title") or "").strip()
            link = (item.get("link") or "").strip()
            publisher = (item.get("publisher") or "").strip()
            if not title and not link:
                continue
            news_items.append({
                "title": title,
                "publisher": publisher,
                "link": link,
                "published": item.get("providerPublishTime", 0),
            })
    except Exception:
        pass
    return {"name": name, "headlines": news_items} if news_items else None


def main():
    symbols = [s["yf"] for s in C25]
    tickers = yf.Tickers(" ".join(symbols))
    stocks = {}
    all_news = {}

    for stock in C25:
        sym = stock["yf"]
        name = stock["name"]
        try:
            ticker = tickers.tickers[sym]
            stocks[sym] = build_stock(name, ticker)
            news = fetch_news(ticker, name)
            if news:
                all_news[sym] = news
        except Exception as e:
            stocks[sym] = {"name": name, "error": str(e)}

    ok = sum(1 for v in stocks.values() if "error" not in v)
    out = {
        "date": str(date.today()),
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "universe": len(C25),
        "fetched_ok": ok,
        "stocks": stocks,
        "news": all_news,
    }

    os.makedirs("prices", exist_ok=True)
    with open("prices/latest.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"Priser+TA gemt lokalt: {ok}/{len(C25)} aktier")


if __name__ == "__main__":
    main()
