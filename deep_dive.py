"""
Laver en grundig første analyse af et nyt selskab.
Kaldes automatisk af bot.py når et selskab dukker op for første gang.
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

import anthropic
import knowledge_manager as km

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def ask_claude(prompt):
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


def run_script(script):
    result = subprocess.run(
        [sys.executable, os.path.join(SCRIPT_DIR, script)],
        capture_output=True, text=True, cwd=SCRIPT_DIR,
    )
    return result.stdout.strip()


def _parse_json(response):
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', response, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return {}


def deep_dive(symbol, name):
    print(f"[deep_dive] Starter analyse af {name} ({symbol}) ...")
    news_json = run_script("news.py")

    prompt = f"""Du er en erfaren finansanalytiker der laver en grundig analyse af {name} (børssymbol: {symbol}).

AKTUELLE NYHEDER FRA MARKEDET:
{news_json}

Lav en komplet analyse i præcis dette JSON-format:

{{
  "overview": "2-3 sætninger om forretningsmodel, kerneprodukt og markedsposition",
  "financials": {{
    "summary": "Nøgletal fra seneste kendte regnskab: omsætning, vækst, EBIT-margin, P/E, udbytte, gæld/egenkapital. Angiv altid regnskabsperiode.",
    "revenue_trend": "Stigende/Faldende/Stabil og kort begrundelse",
    "earnings_trend": "Stigende/Faldende/Stabil og kort begrundelse",
    "key_risks": "Top 3 risici adskilt med semikolon",
    "key_opportunities": "Top 3 muligheder adskilt med semikolon"
  }},
  "news_summary": "Vigtigste begivenheder de seneste 6 måneder som en aktiehandler bør kende til"
}}

Svar KUN med JSON-objektet, ingen forklarende tekst udenfor."""

    analysis = _parse_json(ask_claude(prompt))
    now = datetime.now(timezone.utc).isoformat()

    kb = km.load(symbol) or {}
    kb.update({
        "symbol": symbol, "name": name,
        "deep_dive_completed": now, "last_updated": now,
        "overview": analysis.get("overview", ""),
        "financials": {
            "last_updated": now,
            **analysis.get("financials", {}),
        },
    })
    if "news" not in kb:
        kb["news"] = []
    if analysis.get("news_summary"):
        kb["news"].insert(0, {
            "date": now,
            "title": f"Deep dive sammenfatning — {name}",
            "source": "Intern analyse",
            "summary": analysis["news_summary"],
        })

    km.save(symbol, kb)
    print(f"[deep_dive] Gemt: knowledge/{symbol.replace(':', '_')}.json")
    return kb


def refresh_financials(symbol, name):
    print(f"[deep_dive] Opdaterer regnskabsdata for {name} ...")

    prompt = f"""Opdater regnskabsdata for {name} ({symbol}).

Svar KUN med dette JSON-objekt:
{{
  "summary": "Nøgletal fra seneste kendte regnskab inkl. periode",
  "revenue_trend": "Stigende/Faldende/Stabil og kort begrundelse",
  "earnings_trend": "Stigende/Faldende/Stabil og kort begrundelse",
  "key_risks": "Top 3 risici adskilt med semikolon",
  "key_opportunities": "Top 3 muligheder adskilt med semikolon"
}}"""

    financials = _parse_json(ask_claude(prompt))
    if not financials:
        return

    kb = km.load(symbol) or {"symbol": symbol, "name": name, "news": []}
    kb["financials"] = {"last_updated": datetime.now(timezone.utc).isoformat(), **financials}
    kb["last_updated"] = datetime.now(timezone.utc).isoformat()
    km.save(symbol, kb)
    print(f"[deep_dive] Regnskab opdateret for {name}")


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        deep_dive(sys.argv[1], sys.argv[2])
    else:
        print("Brug: python deep_dive.py <saxo_symbol> <navn>")
        print("Eks:  python deep_dive.py NOVOb:xcse 'Novo Nordisk B'")
