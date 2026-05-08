"""
Henter finansielle nyheder om C25-aktier via yfinance.
Gemmer i videnbasen og printer JSON til stdout.
"""
import json
import sys
from datetime import datetime, timezone

import yfinance as yf

import knowledge_manager as km
from watchlist import C25


def fetch_stock_news(yf_symbol, limit=10):
    try:
        t = yf.Ticker(yf_symbol)
        raw = t.news or []
        articles = []
        for item in raw[:limit]:
            c = item.get("content", {})
            title = c.get("title", "").strip()
            if not title:
                continue
            articles.append({
                "title": title,
                "date": c.get("pubDate", "")[:10] or datetime.now(timezone.utc).date().isoformat(),
                "source": c.get("provider", {}).get("displayName", "Yahoo Finance"),
                "description": (c.get("summary") or "")[:400],
                "url": (c.get("canonicalUrl") or {}).get("url", ""),
            })
        return articles
    except Exception as e:
        print(f"[news] Fejl for {yf_symbol}: {e}", file=sys.stderr)
        return []


def main():
    all_news = []
    total_added = 0

    for s in C25:
        articles = fetch_stock_news(s["yf"])
        if not articles:
            continue

        added = km.add_news(s["saxo"], s["name"], articles)
        if added:
            total_added += added
            print(f"[news] {added} nye artikler gemt for {s['name']}", file=sys.stderr)

        for a in articles:
            all_news.append({**a, "stock": s["name"], "symbol": s["saxo"]})

    result = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "total_new_saved": total_added,
        "articles": all_news[:50],
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
