"""
Manages the knowledge base for each stock in the watchlist.
One JSON file per company under us/knowledge/<symbol>.json
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
from datetime import datetime, timezone, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
KNOWLEDGE_DIR = os.path.join(SCRIPT_DIR, "knowledge")
NEWS_MAX_AGE_DAYS = 60
FINANCIALS_REFRESH_DAYS = 30


def _path(symbol):
    safe = symbol.replace(":", "_").replace("/", "_").replace(" ", "_").replace(".", "_")
    return os.path.join(KNOWLEDGE_DIR, f"{safe}.json")


def load(symbol):
    p = _path(symbol)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return None


def save(symbol, kb):
    os.makedirs(KNOWLEDGE_DIR, exist_ok=True)
    with open(_path(symbol), "w", encoding="utf-8") as f:
        json.dump(kb, f, ensure_ascii=False, indent=2)


def needs_deep_dive(symbol):
    kb = load(symbol)
    return kb is None or not kb.get("deep_dive_completed")


def financials_need_refresh(symbol):
    kb = load(symbol)
    if not kb:
        return True
    ts = kb.get("financials", {}).get("last_updated")
    if not ts:
        return True
    try:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(ts)
        return age.days >= FINANCIALS_REFRESH_DAYS
    except ValueError:
        return True


def prune_news(news_list):
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


def add_news(symbol, name, articles):
    """Add new articles to the knowledge base, drop duplicates and stale news."""
    kb = load(symbol) or {
        "symbol": symbol, "name": name,
        "overview": "", "financials": {}, "news": [],
    }
    by_title = {n["title"]: n for n in kb.get("news", [])}
    added = 0
    for a in articles:
        title = a.get("title", "")
        if not title:
            continue
        if title in by_title:
            # Backfill missing url on existing article
            entry = by_title[title]
            if not entry.get("url") and a.get("url"):
                entry["url"] = a["url"]
            continue
        entry = {
            "date": a.get("date", datetime.now(timezone.utc).isoformat()),
            "title": title,
            "source": a.get("source", ""),
            "summary": (a.get("description") or "")[:400],
            "url": a.get("url", ""),
        }
        kb["news"].append(entry)
        by_title[title] = entry
        added += 1
    kb["news"] = sorted(prune_news(kb["news"]), key=lambda x: x.get("date", ""), reverse=True)
    if added:
        kb["last_updated"] = datetime.now(timezone.utc).isoformat()
    save(symbol, kb)
    return added


def get_prompt_block(symbol):
    """Return a text block that can be inserted into the Claude prompt."""
    kb = load(symbol)
    if not kb:
        return ""

    lines = [f"--- {kb.get('name', symbol)} ---"]

    if kb.get("overview"):
        lines.append(f"Company: {kb['overview']}")

    fin = kb.get("financials", {})
    if fin.get("summary"):
        lines.append(f"Financials (as of {fin.get('last_updated','?')[:10]}): {fin['summary']}")
    if fin.get("key_risks"):
        lines.append(f"Risks: {fin['key_risks']}")
    if fin.get("key_opportunities"):
        lines.append(f"Opportunities: {fin['key_opportunities']}")

    news = kb.get("news", [])
    if news:
        lines.append("News (newest first):")
        for n in news[:8]:
            lines.append(f"  [{n['date'][:10]}] [{n['source']}] {n['title']}")
            if n.get("summary"):
                lines.append(f"    {n['summary'][:200]}")

    return "\n".join(lines)
