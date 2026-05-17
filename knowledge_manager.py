"""
Håndterer videnbasen for hver aktie i watchlisten.
Én JSON-fil per selskab under knowledge/<symbol>.json
"""
import json
import os
from datetime import datetime, timezone, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
KNOWLEDGE_DIR = os.path.join(SCRIPT_DIR, "knowledge")
NEWS_MAX_AGE_DAYS = 60
FINANCIALS_REFRESH_DAYS = 30


def _path(symbol):
    safe = symbol.replace(":", "_").replace("/", "_").replace(" ", "_")
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
    """Tilføj nye artikler til videnbasen, fjern dubletter og gamle nyheder."""
    kb = load(symbol) or {
        "symbol": symbol, "name": name,
        "overview": "", "financials": {}, "news": [],
    }
    existing = {n["title"] for n in kb.get("news", [])}
    added = 0
    for a in articles:
        title = a.get("title", "")
        if title and title not in existing:
            kb["news"].append({
                "date": a.get("date", datetime.now(timezone.utc).isoformat()),
                "title": title,
                "source": a.get("source", ""),
                "summary": (a.get("description") or "")[:400],
                "url": a.get("url", ""),
            })
            existing.add(title)
            added += 1
    kb["news"] = sorted(prune_news(kb["news"]), key=lambda x: x.get("date", ""), reverse=True)
    if added:
        kb["last_updated"] = datetime.now(timezone.utc).isoformat()
    save(symbol, kb)
    return added


def get_prompt_block(symbol):
    """Returnerer en tekstblok der kan indsættes i Claude-prompten."""
    kb = load(symbol)
    if not kb:
        return ""

    lines = [f"--- {kb.get('name', symbol)} ---"]

    if kb.get("overview"):
        lines.append(f"Virksomhed: {kb['overview']}")

    fin = kb.get("financials", {})
    if fin.get("summary"):
        lines.append(f"Regnskab (pr. {fin.get('last_updated','?')[:10]}): {fin['summary']}")
    if fin.get("key_risks"):
        lines.append(f"Risici: {fin['key_risks']}")
    if fin.get("key_opportunities"):
        lines.append(f"Muligheder: {fin['key_opportunities']}")

    news = kb.get("news", [])
    if news:
        lines.append("Nyheder (nyeste først):")
        for n in news[:8]:
            lines.append(f"  [{n['date'][:10]}] [{n['source']}] {n['title']}")
            if n.get("summary"):
                lines.append(f"    {n['summary'][:200]}")

    return "\n".join(lines)
