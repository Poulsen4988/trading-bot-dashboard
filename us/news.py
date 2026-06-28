"""
Fetches financial news for the US S&P-500 paper-trading bot via yfinance.
Instead of all ~500 symbols, fetches ONLY for the DEEP SET
(screening.top + screening.scouts + current portfolio positions) to stay light.
Per symbol it incrementally builds us/knowledge/<TICKER>.json via github_store.
Prints a JSON summary to stdout.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
import time
from datetime import datetime, timezone, timedelta

import yfinance as yf

import github_store as gh
from watchlist import YF_TO_NAME

NEWS_MAX_AGE_DAYS = 60


def _today():
    return datetime.now(timezone.utc).date().isoformat()


def _ticker_path(yf_symbol):
    safe = yf_symbol.replace(".", "_").replace("/", "_")
    return f"us/knowledge/{safe}.json"


def fetch_stock_news(yf_symbol, limit=10):
    raw = None
    for attempt in range(3):
        try:
            raw = yf.Ticker(yf_symbol).news or []
            break
        except Exception as e:
            if attempt == 2:
                print(f"[news] Error for {yf_symbol}: {e}", file=sys.stderr)
                return []
            time.sleep(2 * (attempt + 1))
    try:
        articles = []
        for item in (raw or [])[:limit]:
            c = item.get("content", {})
            title = (c.get("title") or "").strip()
            if not title:
                continue
            articles.append({
                "title": title,
                "date": c.get("pubDate", "")[:10] or _today(),
                "source": c.get("provider", {}).get("displayName", "Yahoo Finance"),
                "description": (c.get("summary") or "")[:400],
                "url": (c.get("canonicalUrl") or {}).get("url", ""),
            })
        return articles
    except Exception as e:
        print(f"[news] Error for {yf_symbol}: {e}", file=sys.stderr)
        return []


def _prune_news(news_list):
    cutoff = datetime.now(timezone.utc) - timedelta(days=NEWS_MAX_AGE_DAYS)
    result = []
    for item in news_list:
        try:
            raw = item["date"].replace("Z", "+00:00")
            if len(raw) == 10:
                raw += "T00:00:00+00:00"
            d = datetime.fromisoformat(raw)
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            if d >= cutoff:
                result.append(item)
        except (ValueError, KeyError):
            result.append(item)
    return result


def add_news(yf_symbol, name, articles):
    """Load us/knowledge/<TICKER>.json, append new articles deduped by
    url and title+date, prune old, push back. Returns count of new items."""
    kb, _ = gh.get_json(_ticker_path(yf_symbol), default=None)
    if not kb:
        kb = {"symbol": yf_symbol, "name": name, "overview": "",
              "financials": {}, "news": []}
    kb.setdefault("news", [])
    kb.setdefault("symbol", yf_symbol)
    kb.setdefault("name", name)

    seen_urls = {n.get("url") for n in kb["news"] if n.get("url")}
    by_title_date = {(n.get("title", ""), n.get("date", "")[:10]): n for n in kb["news"]}
    added = 0
    for a in articles:
        title = a.get("title", "")
        if not title:
            continue
        url = a.get("url", "")
        date10 = (a.get("date") or "")[:10]
        if url and url in seen_urls:
            continue
        if (title, date10) in by_title_date:
            entry = by_title_date[(title, date10)]
            if not entry.get("url") and url:
                entry["url"] = url
                seen_urls.add(url)
            continue
        entry = {
            "date": a.get("date") or datetime.now(timezone.utc).isoformat(),
            "title": title,
            "source": a.get("source", ""),
            "summary": (a.get("description") or "")[:400],
            "url": url,
        }
        kb["news"].append(entry)
        by_title_date[(title, date10)] = entry
        if url:
            seen_urls.add(url)
        added += 1

    kb["news"] = sorted(_prune_news(kb["news"]),
                        key=lambda x: x.get("date", ""), reverse=True)
    if added:
        kb["last_updated"] = datetime.now(timezone.utc).isoformat()
        gh.put_json(_ticker_path(yf_symbol), kb,
                    f"US bot: news update {yf_symbol} (+{added})")
    return added


def _deep_set():
    """screening.top + screening.scouts + current portfolio positions."""
    symbols = []
    seen = set()

    def add(sym):
        if sym and sym not in seen:
            seen.add(sym)
            symbols.append(sym)

    screening, _ = gh.get_json(f"us/screening/{_today()}.json", default=None)
    if screening:
        for sym in (screening.get("top") or []):
            add(sym)
        for sym in (screening.get("scouts") or []):
            add(sym)

    data, _ = gh.get_json("us/data.json", default=None)
    if data:
        for pos in (data.get("portfolio", {}).get("positions") or []):
            add(pos.get("symbol"))

    return symbols


def main():
    deep = _deep_set()
    if not deep:
        print("[news] Deep set empty (no screening/portfolio yet); nothing to fetch.",
              file=sys.stderr)

    all_news = []
    total_added = 0

    for sym in deep:
        try:
            name = YF_TO_NAME.get(sym, sym)
            articles = fetch_stock_news(sym)
            if not articles:
                continue
            added = add_news(sym, name, articles)
            if added:
                total_added += added
                print(f"[news] {added} new articles saved for {name}", file=sys.stderr)
            for a in articles:
                all_news.append({**a, "stock": name, "symbol": sym})
        except Exception as e:
            print(f"[news] Skipping {sym}: {e}", file=sys.stderr)
            continue

    result = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "deep_set_size": len(deep),
        "total_new_saved": total_added,
        "articles": all_news[:50],
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
