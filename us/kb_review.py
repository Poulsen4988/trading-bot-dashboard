"""
KB Review (US) — analyserer us/knowledge/*.json for dubletter, stale items og lav-værdi indhold.

Kør: python us/kb_review.py

Scriptet sletter INTET selv. Det printer en kandidat-rapport til stdout som
AI-rutinen kan bruge til at træffe beslutning om hvad der reelt skal fjernes.

Output-struktur:
{
  "date": "YYYY-MM-DD",
  "files_reviewed": int,
  "total_items": int,
  "total_candidates": int,
  "files": [
    {
      "path": "us/knowledge/AAPL.json",
      "symbol": "AAPL",
      "news_count": 42,
      "candidates": [
        {"index": 3, "type": "duplicate_url", "title": "...", "date": "...", "url": "..."},
        {"index": 7, "type": "duplicate_title", "title": "...", "date": "..."},
        {"index": 12, "type": "stale", "title": "...", "date": "...", "age_days": 220},
        {"index": 15, "type": "low_value", "title": "...", "date": "...", "reason": "empty summary"}
      ]
    }
  ]
}
"""
from __future__ import annotations

import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
from collections import defaultdict
from datetime import date, datetime, timezone

# Al GitHub-kommunikation via github_store (API med lokal-klon fallback, så
# scriptet også virker i rutine-sandkassen hvor api.github.com er blokeret).
import github_store

STALE_DAYS = 180
LOW_VALUE_SUMMARY_LEN = 30


def list_dir(path: str):
    names = github_store.list_dir(path)
    if not names:
        print(f"[kb_review] kunne ikke liste {path} (eller mappen er tom)", file=sys.stderr)
    return [{"name": n, "path": f"{path}/{n}"} for n in names]


def fetch_json(path: str):
    data, _ = github_store.get_json(path, default=None)
    if data is None:
        print(f"[kb_review] kunne ikke hente {path}", file=sys.stderr)
    return data


def parse_date(s):
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except Exception:
        return None


def review_news(news_items):
    """Identificer dublet/stale/low-value kandidater i en news-liste."""
    candidates = []
    seen_urls = {}
    by_title_date = defaultdict(list)
    today = date.today()

    for i, n in enumerate(news_items or []):
        url = (n.get("url") or "").strip()
        title = (n.get("title") or "").strip()
        date_str = str(n.get("date") or "")[:10]
        summary = (n.get("summary") or "").strip()

        # Duplicate URL — første ses holdes, øvrige markeres
        if url:
            if url in seen_urls:
                candidates.append({
                    "index": i, "type": "duplicate_url",
                    "title": title, "date": date_str, "url": url,
                    "first_seen_index": seen_urls[url],
                })
            else:
                seen_urls[url] = i

        # Nær-dublet titel samme dag
        if title:
            key = (title.lower()[:80], date_str)
            by_title_date[key].append(i)

        # Stale (> STALE_DAYS dage)
        d = parse_date(date_str)
        if d:
            age = (today - d).days
            if age > STALE_DAYS:
                candidates.append({
                    "index": i, "type": "stale",
                    "title": title, "date": date_str, "age_days": age,
                })

        # Lav-værdi (tom eller meget kort summary)
        if not summary or len(summary) < LOW_VALUE_SUMMARY_LEN:
            candidates.append({
                "index": i, "type": "low_value",
                "title": title, "date": date_str,
                "summary_len": len(summary),
                "reason": "empty summary" if not summary else f"summary < {LOW_VALUE_SUMMARY_LEN} chars",
            })

    # Title duplikater
    for (norm_title, _d), indices in by_title_date.items():
        if len(indices) > 1 and norm_title:
            for i in indices[1:]:
                candidates.append({
                    "index": i, "type": "duplicate_title",
                    "title": news_items[i].get("title"),
                    "date": str(news_items[i].get("date") or "")[:10],
                    "first_seen_index": indices[0],
                })

    return candidates


def main():
    today_str = date.today().isoformat()
    listing = list_dir("us/knowledge")
    json_files = [f for f in listing if f.get("name", "").endswith(".json")]

    file_reports = []
    total_items = 0
    total_candidates = 0

    for f in json_files:
        path = f.get("path") or f"us/knowledge/{f.get('name')}"
        kb = fetch_json(path)
        if not isinstance(kb, dict):
            continue
        news = kb.get("news", []) or []
        candidates = review_news(news)
        if not candidates:
            continue
        total_items += len(news)
        total_candidates += len(candidates)
        file_reports.append({
            "path": path,
            "symbol": kb.get("symbol") or path.replace("us/knowledge/", "").replace(".json", ""),
            "news_count": len(news),
            "candidates": candidates,
        })

    output = {
        "date": today_str,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "stale_days_threshold": STALE_DAYS,
        "low_value_summary_threshold_chars": LOW_VALUE_SUMMARY_LEN,
        "files_reviewed": len(json_files),
        "files_with_candidates": len(file_reports),
        "total_items": total_items,
        "total_candidates": total_candidates,
        "instructions": (
            "Gennemgå candidates pr. fil. For hver kandidat: vurder OM det reelt er "
            "unødigt (duplikat med ingen yderligere info, eller stale UDEN langsigtet "
            "værdi). Slet KUN det du er sikker på er unødigt. Behold materielt vigtigt "
            "også selv om det er gammelt (fx tidligere milestone-nyheder, "
            "strukturelle ændringer). Skriv en us/knowledge_cleanup_reports/DATO.json med dine "
            "valg, og upload kun de filer du har faktisk renset."
        ),
        "files": file_reports,
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
