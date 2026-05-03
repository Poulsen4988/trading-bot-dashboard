"""
Hoved-bot: køres af GitHub Actions (eller lokalt til test).
Kald med argument: python bot.py [premarket|open|midday|close]
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

import anthropic
import knowledge_manager as km
from watchlist import C25, WATCHLIST

LOG_FILE = "journal.jsonl"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def run_script(script):
    result = subprocess.run(
        [sys.executable, os.path.join(SCRIPT_DIR, script)],
        capture_output=True, text=True, cwd=SCRIPT_DIR,
    )
    return result.stdout.strip()


def ask_claude(prompt):
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


def log_entry(entry):
    entry["timestamp"] = datetime.now(timezone.utc).isoformat()
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


def run_premarket():
    print("=== PRE-MARKET ANALYSE ===")
    ensure_knowledge()
    news_json = run_script("news.py")
    market_json = run_script("research.py")
    knowledge = build_knowledge_block()

    prompt = f"""Du er en disciplineret aktiehandler der analyserer C25-indekset.

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
    log_entry({"action": "PREMARKET", "analyse": analyse, "reason": "Pre-market nyhedsanalyse"})
    run_script("sync_dashboard.py")
    run_script("gist_update.py")


def run_market_open():
    print("=== MARKEDSÅBNING ===")
    ensure_knowledge()
    market_json = run_script("research.py")
    news_json = run_script("news.py")
    knowledge = build_knowledge_block()

    prompt = f"""Du er en disciplineret aktiehandler med adgang til Saxo Bank.

{knowledge}

MARKEDSDATA (alle C25-aktier):
{market_json}

AKTUELLE NYHEDER:
{news_json}

Analyser situationen og tag én beslutning.
Du kan KUN handle aktier med kendte UIC-koder: {tradeable_list()}

- Køb: {{"action": "BUY", "uic": <nummer>, "symbol": "<navn>", "amount": <antal>, "reason": "<begrundelse>"}}
- Sælg: {{"action": "SELL", "uic": <nummer>, "symbol": "<navn>", "amount": <antal>, "reason": "<begrundelse>"}}
- Vent: {{"action": "HOLD", "reason": "<begrundelse>"}}

Regler: maks 10 aktier per handel, maks 3 åbne positioner, sælg ved -5% tab.
Svar KUN med JSON-objektet."""

    response = ask_claude(prompt)
    print(f"Claude beslutning: {response}")

    try:
        decision = json.loads(response)
    except json.JSONDecodeError:
        log_entry({"action": "ERROR", "reason": f"Kunne ikke parse svar: {response}"})
        return

    action = decision.get("action", "HOLD").upper()
    if action in ("BUY", "SELL"):
        uic = decision.get("uic")
        amount = decision.get("amount", 1)
        trade_result = subprocess.run(
            [sys.executable, os.path.join(SCRIPT_DIR, "trade.py"), action, str(uic), str(amount)],
            capture_output=True, text=True, cwd=SCRIPT_DIR,
        )
        print(f"Trade resultat: {trade_result.stdout}")
        log_entry({
            "action": action, "symbol": decision.get("symbol"),
            "uic": uic, "amount": amount, "reason": decision.get("reason"),
            "trade_response": trade_result.stdout[:500],
        })
    else:
        log_entry({"action": "HOLD", "reason": decision.get("reason", "Ingen handling")})

    run_script("sync_dashboard.py")
    run_script("gist_update.py")


def run_midday():
    print("=== MIDDAG CHECK ===")
    market_json = run_script("research.py")
    knowledge = build_knowledge_block()

    prompt = f"""Du er en aktiehandler med åbne positioner i C25-aktier.

{knowledge}

AKTUELLE POSITIONER OG KURSER:
{market_json}

Gennemgå positionerne:
- Er der nogen position der er faldet mere end 5%? (sælg straks)
- Er der andre ændringer der kræver handling?

Handlebare aktier: {tradeable_list()}

Svar med JSON: {{"action": "BUY/SELL/HOLD", "uic": <eller null>, "symbol": "<eller null>", "amount": <eller 0>, "reason": "<begrundelse>"}}
Svar KUN med JSON."""

    response = ask_claude(prompt)
    print(f"Claude beslutning: {response}")

    try:
        decision = json.loads(response)
    except json.JSONDecodeError:
        log_entry({"action": "ERROR", "reason": f"Parse fejl: {response}"})
        return

    action = decision.get("action", "HOLD").upper()
    if action in ("BUY", "SELL") and decision.get("uic"):
        subprocess.run(
            [sys.executable, os.path.join(SCRIPT_DIR, "trade.py"),
             action, str(decision["uic"]), str(decision.get("amount", 1))],
            cwd=SCRIPT_DIR,
        )
    log_entry({"action": action, "symbol": decision.get("symbol"), "reason": decision.get("reason")})
    run_script("sync_dashboard.py")
    run_script("gist_update.py")


def run_close():
    print("=== DAGENS AFSLUTNING ===")
    market_json = run_script("research.py")
    knowledge = build_knowledge_block()

    with open(os.path.join(SCRIPT_DIR, LOG_FILE), "r", encoding="utf-8") as f:
        todays_log = [l for l in f.readlines() if datetime.now().strftime("%Y-%m-%d") in l]

    prompt = f"""Afslut handelsdagen som en disciplineret aktiehandler.

{knowledge}

SLUTKURSER OG POSITIONER:
{market_json}

DAGENS HANDLER:
{"".join(todays_log[-10:])}

Lav en kort dagsoversigt (maks 150 ord):
1. Hvad handlede du i dag og hvorfor?
2. Hvad er resultatet?
3. Hvad holder du over natten og hvorfor?

Svar på dansk."""

    summary = ask_claude(prompt)
    print(summary)
    log_entry({"action": "EOD_SUMMARY", "reason": summary})
    run_script("sync_dashboard.py")
    run_script("gist_update.py")


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
