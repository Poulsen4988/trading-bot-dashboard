"""
Hoved-bot til analyse/paper trading.

Kald med argument: python bot.py [premarket|open|midday|close]

Botten laver analyser og anbefalinger, logger dem i journal.jsonl og opdaterer
dashboardet. Den sender ingen live-ordrer og bruger ikke Saxo.
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

import anthropic
import knowledge_manager as km
import risk_manager
from watchlist import C25, WATCHLIST

LOG_FILE = "journal.jsonl"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def run_script(script):
    result = subprocess.run(
        [sys.executable, os.path.join(SCRIPT_DIR, script)],
        capture_output=True, text=True, cwd=SCRIPT_DIR,
    )
    if result.stderr:
        print(result.stderr.strip(), file=sys.stderr)
    return result.stdout.strip()


def ask_claude(prompt):
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


def parse_json_object(text):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise


def load_market():
    raw = run_script("research.py")
    try:
        return json.loads(raw), raw
    except json.JSONDecodeError:
        return {"error": "Kunne ikke parse research.py output", "raw": raw}, raw


def log_entry(entry):
    entry = dict(entry)
    entry.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    with open(os.path.join(SCRIPT_DIR, LOG_FILE), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"[{entry['timestamp']}] {entry.get('action', 'LOG')}: {entry.get('reason', '')}")


def ensure_knowledge():
    import deep_dive as dd
    for s in C25:
        symbol, name = s["saxo"], s["name"]
        if km.needs_deep_dive(symbol):
            print(f"[bot] Nyt selskab — starter deep dive: {name}")
            dd.deep_dive(symbol, name)
        elif km.financials_need_refresh(symbol):
            print(f"[bot] Regnskab forældet — opdaterer: {name}")
            dd.refresh_financials(symbol, name)


def build_knowledge_block():
    blocks = [km.get_prompt_block(s["saxo"]) for s in C25]
    blocks = [b for b in blocks if b]
    if not blocks:
        return ""
    return "VIDENBASE OM SELSKABERNE:\n" + "\n\n".join(blocks)


def tradeable_list():
    return ", ".join(f"{s['name']}={s['uic']}" for s in WATCHLIST)


def sync_outputs():
    run_script("sync_dashboard.py")


def run_premarket():
    print("=== PRE-MARKET ANALYSE ===")
    ensure_knowledge()
    news_json = run_script("news.py")
    market, market_json = load_market()
    knowledge = build_knowledge_block()

    prompt = f"""Du er en disciplineret aktieanalytiker der analyserer C25-indekset.

{knowledge}

SENESTE NYHEDER:
{news_json}

MARKEDSDATA:
{market_json}

Lav en kort pre-market analyse (maks 200 ord):
1. Er der nyheder der påvirker C25-selskaberne?
2. Hvad er din overordnede markedsforventning i dag?
3. Hvilke aktier følger du tættest ved åbning?

Svar på dansk. Vær konkret og kortfattet."""

    analyse = ask_claude(prompt)
    print(analyse)
    log_entry({"action": "PREMARKET", "analyse": analyse, "reason": "Pre-market nyhedsanalyse", "execution": "none"})
    sync_outputs()


def run_market_open():
    print("=== MARKEDSÅBNING ===")
    ensure_knowledge()
    market, market_json = load_market()
    news_json = run_script("news.py")
    knowledge = build_knowledge_block()

    prompt = f"""Du er en disciplineret aktieanalytiker. Du laver paper-trading/anbefalinger, ikke live handler.

{knowledge}

MARKEDSDATA (alle C25-aktier):
{market_json}

AKTUELLE NYHEDER:
{news_json}

Analyser situationen og tag én beslutning.
Du kan KUN anbefale aktier med kendte UIC-koder: {tradeable_list()}

Vælg kun BUY eller SELL hvis der er en tydelig, konkret edge. Ellers vælg HOLD.
Regler:
- Ingen tvangssalg ved et fast procenttab; vurder om den oprindelige thesis er brudt.
- Ingen fast grænse på antal åbne positioner; vurder koncentrationsrisiko.
- Undgå enkeltidéer over ca. 25% af porteføljen.
- Vær konservativ ved manglende pris-, nyheds- eller regnskabsdata.
- Dette er analyse/paper trading og må ikke beskrives som en udført live handel.

Svar KUN med JSON:
{{
  "action": "BUY/SELL/HOLD",
  "uic": <nummer eller null>,
  "symbol": "<symbol eller null>",
  "name": "<selskabsnavn eller null>",
  "amount": <foreslået antal eller 0>,
  "reason": "<kort begrundelse>",
  "reasoning": {{
    "bull": "<stærkeste argument for>",
    "bear": "<stærkeste argument imod>",
    "verdict": "BUY/SELL/HOLD",
    "confidence": <1-10>,
    "summary": "<kort konklusion>"
  }}
}}"""

    response = ask_claude(prompt)
    print(f"Claude beslutning: {response}")

    try:
        decision = parse_json_object(response)
    except Exception:
        log_entry({"action": "ERROR", "reason": f"Kunne ikke parse svar: {response}", "execution": "none"})
        return

    normalized = risk_manager.normalize_decision(decision, market)
    log_entry(normalized)
    sync_outputs()


def run_midday():
    print("=== MIDDAG CHECK ===")
    market, market_json = load_market()
    knowledge = build_knowledge_block()
    risk_flags = risk_manager.review_portfolio_risk(market)

    prompt = f"""Du er en aktieanalytiker der overvåger en paper-trading portefølje.

{knowledge}

AKTUELLE POSITIONER OG KURSER:
{market_json}

RISIKOFLAG FRA KODEN:
{json.dumps(risk_flags, ensure_ascii=False, indent=2)}

Gennemgå porteføljen:
- Er en thesis brudt?
- Er der overkoncentration eller ny informationsrisiko?
- Er der en grund til at reducere, øge eller holde?

Handlebare/anbefalbare aktier: {tradeable_list()}

Svar KUN med JSON:
{{"action": "BUY/SELL/HOLD", "uic": <eller null>, "symbol": "<eller null>", "name": "<eller null>", "amount": <eller 0>, "reason": "<begrundelse>", "reasoning": {{"verdict": "BUY/SELL/HOLD", "confidence": <1-10>, "summary": "<kort>"}}}}"""

    response = ask_claude(prompt)
    print(f"Claude beslutning: {response}")

    try:
        decision = parse_json_object(response)
    except Exception:
        log_entry({"action": "ERROR", "reason": f"Parse fejl: {response}", "execution": "none"})
        return

    log_entry(risk_manager.normalize_decision(decision, market))
    sync_outputs()


def run_close():
    print("=== DAGENS AFSLUTNING ===")
    market, market_json = load_market()
    knowledge = build_knowledge_block()

    try:
        with open(os.path.join(SCRIPT_DIR, LOG_FILE), "r", encoding="utf-8") as f:
            todays_log = [l for l in f.readlines() if datetime.now().strftime("%Y-%m-%d") in l]
    except FileNotFoundError:
        todays_log = []

    prompt = f"""Afslut handelsdagen som en disciplineret aktieanalytiker.

{knowledge}

SLUTKURSER OG POSITIONER:
{market_json}

DAGENS BESLUTNINGER:
{"".join(todays_log[-10:])}

Lav en kort dagsoversigt (maks 150 ord):
1. Hvilke anbefalinger kom i dag og hvorfor?
2. Hvad er status på porteføljen?
3. Hvad bør følges næste handelsdag?

Svar på dansk."""

    summary = ask_claude(prompt)
    print(summary)
    log_entry({"action": "EOD_SUMMARY", "reason": summary, "execution": "none"})
    sync_outputs()


MODES = {
    "premarket": run_premarket,
    "open": run_market_open,
    "midday": run_midday,
    "close": run_close,
}

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "open"
    if mode not in MODES:
        print(f"Ukendt mode: {mode}. Valgmuligheder: {list(MODES.keys())}")
        sys.exit(1)
    MODES[mode]()
