"""
Henter finansielle nyheder om watchlist-aktier via RSS feeds.
Gemmer daterede nyheder i videnbasen og printer JSON til stdout.
"""
import json
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import knowledge_manager as km

FEEDS = [
    {"name": "Euroinvestor", "url": "https://www.euroinvestor.dk/rss/nyheder"},
    {"name": "Nasdaq Copenhagen", "url": "https://www.nasdaqomxnordic.com/news/companynews/rss"},
]


def get_watchlist():
    """Henter watchlist fra research.py — ét sted at opdatere."""
    try:
        import research
        return research.WATCHLIST
    except Exception:
        return []


def build_keywords(watchlist):
    """Genererer søgeord fra watchlist-navne og symboler."""
    keywords = set()
    for stock in watchlist:
        name = stock.get("name", "")
        symbol = stock.get("symbol", "")
        if name:
            keywords.add(name)
            # Tilføj første ord af navn (fx "Novo" fra "Novo Nordisk")
            first_word = name.split()[0]
            if len(first_word) > 3:
                keywords.add(first_word)
        if symbol:
            ticker = symbol.split(":")[0].upper()
            if len(ticker) > 2:
                keywords.add(ticker)
    return list(keywords)


def parse_date(date_str):
    """Parser RSS pubDate til ISO-format."""
    if not date_str:
        return datetime.now(timezone.utc).isoformat()
    try:
        return parsedate_to_datetime(date_str).isoformat()
    except Exception:
        return datetime.now(timezone.utc).isoformat()


def fetch_feed(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read()
    except Exception:
        return None


def parse_feed(xml_bytes):
    items = []
    try:
        root = ET.fromstring(xml_bytes)
        for item in root.iter("item"):
            title = item.findtext("title", "").strip()
            link = item.findtext("link", "").strip()
            pub = item.findtext("pubDate", "").strip()
            desc = item.findtext("description", "").strip()
            items.append({
                "title": title,
                "link": link,
                "date": parse_date(pub),
                "description": desc[:400],
            })
    except Exception:
        pass
    return items


def filter_relevant(items, keywords):
    relevant = []
    for item in items:
        text = (item["title"] + " " + item["description"]).upper()
        if any(kw.upper() in text for kw in keywords):
            relevant.append(item)
    return relevant


def main():
    watchlist = get_watchlist()
    keywords = build_keywords(watchlist)

    all_news = []
    for feed in FEEDS:
        xml_bytes = fetch_feed(feed["url"])
        if xml_bytes:
            items = parse_feed(xml_bytes)
            relevant = filter_relevant(items, keywords)
            for item in relevant:
                item["source"] = feed["name"]
                all_news.append(item)

    # Gem nyheder i videnbasen per selskab
    for stock in watchlist:
        symbol = stock["symbol"]
        name = stock["name"]
        stock_keywords = build_keywords([stock])
        stock_articles = [
            a for a in all_news
            if any(kw.upper() in (a["title"] + " " + a["description"]).upper()
                   for kw in stock_keywords)
        ]
        if stock_articles:
            added = km.add_news(symbol, name, stock_articles)
            if added:
                print(f"[news] {added} nye artikler gemt for {name}", file=sys.stderr)

    result = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "relevant_articles": all_news[:20],
        "total_found": len(all_news),
        "keywords_searched": keywords,
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
