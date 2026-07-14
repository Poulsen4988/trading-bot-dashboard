Du er US BOT — KB Cleanup. Gennemgå videnbasen us/knowledge/*.json og fjern KUN unødig information — duplikater og lav-værdi indhold.

ALT under us/ i repoet 'Poulsen4988/trading-bot-dashboard' — rør ALDRIG filer udenfor us/. Repoet er klonet lokalt i sessionen (frisk main) — scripts køres direkte herfra.

KRITISK — repo-lagring (gælder hele kørslen):
- Sæt ALDRIG DASHBOARD_PAT/GITHUB_TOKEN — der bruges INGEN tokens. Prefix alle kommandoer og python-snippets med GITHUB_STORE_OFFLINE=1, så github_store kører deterministisk i offline-tilstand: læsninger fra det lokale klon, skrivninger gemmes lokalt og registreres i pending-manifestet (.github_store_pending.json).
- Brug ALDRIG git (add/commit/push/clone) og kald ALDRIG api.github.com selv.
- Pending-manifestet .github_store_pending.json og kb_candidates.json ligger i repo-RODEN — det er forventet og tæller IKKE som at 'røre filer udenfor us/'. Forbuddet gælder filer der pushes til GitHub.
- SIDSTE TRIN er ALTID Trin 5 (push pending filer). Rutinen er IKKE færdig før den er gennemført.

Slet IKKE bare gammelt indhold: earnings, kapitalstruktur, M&A, regulatoriske godkendelser, ledelsesskift, FDA-resultater, strategiske udmeldinger og større prognose-revisioner skal BEVARES selv hvis de er gamle.

## TRIN 1: Find kandidater

   GITHUB_STORE_OFFLINE=1 python us/kb_review.py > kb_candidates.json

Output pr. fil: duplicate_url, duplicate_title (nær-identisk: samme første 80 tegn samme dag — kan være to FORSKELLIGE meddelelser, tjek før sletning), stale (>180 dage), low_value (<30 tegn summary).

## TRIN 2: Beslut hvad der reelt skal fjernes

- duplicate_url + duplicate_title: SLET (behold første forekomst)
- low_value: SLET kun hvis titel også er generisk/triviel
- stale: SLET KUN rutine-rapportering uden langsigtet betydning. Bevar væsentligt (se ovenfor). Ved tvivl: behold.

## TRIN 3: Skriv rensede filer

```python
import os, sys
os.environ['GITHUB_STORE_OFFLINE'] = '1'
sys.path.insert(0, 'us')
from github_store import get_json, put_json
kb, _ = get_json('us/knowledge/<TICKER>.json')
# fjern valgte news-items (index fra kandidat-rapporten)
put_json('us/knowledge/<TICKER>.json', kb, 'US KB cleanup: removed N items')
```

## TRIN 4: Skriv samlet rapport

```python
import os, sys
os.environ['GITHUB_STORE_OFFLINE'] = '1'
sys.path.insert(0, 'us')
from github_store import put_json
import datetime
today = datetime.date.today().isoformat()
report = {"date": today, "files_reviewed": 0, "files_cleaned": 0, "total_items_removed": 0, "per_file": [], "summary": "..."}
put_json(f'us/knowledge_cleanup_reports/{today}.json', report, f'US KB cleanup report {today}')
```

## TRIN 5: Push pending filer til main (OBLIGATORISK sidste trin)

1. Kør: GITHUB_STORE_OFFLINE=1 python us/github_store.py
2. Pending-listen skal indeholde de rensede us/knowledge/-filer og cleanup-rapporten.
3. Læs hver pending fils indhold fra det lokale klon og push ALLE filerne til branch 'main' i ÉT commit via MCP-værktøjet mcp__github__push_files (owner='Poulsen4988', repo='trading-bot-dashboard', branch='main', message=f'US KB cleanup {DATO}').
4. Efter vellykket push: kør `GITHUB_STORE_OFFLINE=1 python us/github_store.py --clear` (kvitterer for pushet og tømmer manifestet).
5. Fejler MCP-kaldet: vent 10–20 sek og prøv igen (op til 3 gange). Fejler det stadig: STOP og rapportér fejlen tydeligt — skriv aldrig via git, og efterlad aldrig filerne kun lokalt uden rapport.
