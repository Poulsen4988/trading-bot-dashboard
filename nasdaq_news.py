"""
Henter officielle selskabsmeddelelser fra Nasdaq Copenhagen for C25-aktier.

Supplerer news.py (yfinance) med danske børsmeddelelser — regnskaber,
indsiderhandler, tilbagekøb, guidance mm. Gemmer i samme videnbase via
knowledge_manager. Køres af GitHub Actions.

Ét feed-kald henter alle Copenhagen-meddelelser; hver meddelelse matches
mod C25 via watchlist-feltet 'nasdaq'.
"""
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone

import knowledge_manager as km
from watchlist import C25

FEED_URL = (
    "https://api.news.eu.nasdaq.com/news/query.action"
    "?type=rss&showAttachments=false&showCnsSpecific=true&showCompany=true"
    "&countResults=false&freeText=&company=&market=Main%20Market%2C%20Copenhagen"
    "&cnscategory=&globalGroup=exchangeNotice&globalName=NordicMainMarkets"
    "&displayLanguage=da&language=&timeZone=CET&dateMask=yyyy-MM-dd+HH%3Amm%3Ass"
    "&limit=500&start=0&dir=DESC"
)


def fetch_feed(retries=3, backoff=3):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(FEED_URL, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except Exception as e:
            last = e
            if attempt < retries - 1:
                time.sleep(backoff * (attempt + 1))
    raise last


def to_article(item):
    raw_date = item.get("published") or item.get("releaseTime") or ""
    date = raw_date[:10] if raw_date else datetime.now(timezone.utc).date().isoformat()
    return {
        "title": (item.get("headline") or "").strip(),
        "date": date,
        "source": "Nasdaq Copenhagen",
        "description": item.get("cnsCategory") or "",
        "url": item.get("messageUrl") or "",
    }


def main():
    try:
        feed = fetch_feed()
    except Exception as e:
        print(f"[nasdaq_news] Kunne ikke hente feed: {e}", file=sys.stderr)
        return

    items = feed.get("results", {}).get("item", [])
    if isinstance(items, dict):  # feed returnerer en enkelt dict når kun ét resultat
        items = [items]
    print(f"[nasdaq_news] {len(items)} meddelelser fra Nasdaq Copenhagen", file=sys.stderr)

    total = 0
    for s in C25:
        kw = s.get("nasdaq")
        if not kw:
            continue
        articles = [
            to_article(it) for it in items
            if kw in (it.get("company") or "").lower()
        ]
        articles = [a for a in articles if a["title"]]
        if not articles:
            continue
        added = km.add_news(s["saxo"], s["name"], articles)
        if added:
            total += added
            print(f"[nasdaq_news] {added} nye meddelelser for {s['name']}", file=sys.stderr)

    print(f"[nasdaq_news] Faerdig: {total} nye meddelelser gemt", file=sys.stderr)


if __name__ == "__main__":
    main()
