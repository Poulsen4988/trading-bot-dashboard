# Trading Bot — Start her (ny session)

## Rutine-robusthed 2026-07-13 — offline-tilstand (læs før ændringer)
Rutine-sandkassen blokerer ofte `api.github.com` (403 "GitHub access is not
enabled for this session") — det væltede rutinerne 2026-06-30 → 2026-07-10
(vagthund-issues #3–#17). `github_store.py` er derfor gjort selvhelende:

- **Læse-fallback:** `get_json` prøver API'et og falder tilbage til det
  lokale repo-klon (rutinens klon er frisk main ved sessionstart).
- **Skrive-fallback:** `put_json` gemmer lokalt + registrerer filen i
  `.github_store_pending.json` (gitignored) når API'et fejler. Rutinen
  pusher til sidst alle pending filer til main i ét commit via MCP-værktøjet
  `mcp__github__push_files`. `python github_store.py` printer pending-listen.
- **Circuit breaker:** 401/403 eller gentagne netværksfejl → processen går
  permanent i offline-tilstand (ingen spildte retries).
  `GITHUB_STORE_OFFLINE=1` tvinger offline-tilstand (bruges i rutine-prompts).
- **Write-through:** API-succes skriver også filen lokalt, så senere
  læsninger i samme session aldrig rammer forældet state.
- **Rutine-prompts:** autoritative, PAT-frie versioner ligger i `routines/`
  (se `routines/README.md` for hvordan de sættes på triggerne).
- `us/github_store.py` er en identisk kopi af `github_store.py` — HOLD I SYNK.
- GitHub Actions er uændret: med gyldig token og fungerende API opfører
  github_store sig som før (API med retry + 409-håndtering).

## Optimering 2026-06-09 — nye invarianter (læs før ændringer)
- **data.json er slank.** `trades[]` indeholder kun `{verdict, confidence, summary}`
  — IKKE bull/bear eller investment_plan. Den fulde begrundelse ligger i
  `decisions/DATO.json`; dashboardets handelsmodal henter den on-demand. Tilføj
  ikke tunge felter tilbage til trades. `paper_trader.slim_trades()` håndhæver det.
- **Eneejer-skrivning:** `paper_trader.py` ejer portfolio/cash/positions/history/
  trades. `sync_dashboard.py` skriver KUN afledte felter (stocks, benchmarks,
  sector_exposure_pct, latest_decisions) og tilføjer kun dagens history-punkt hvis
  det mangler. Lad være med at lade dem skrive de samme felter.
- **github_store** har retry + 409-håndtering; `get_json(..., raise_on_error=True)`
  bruges på kritiske reads så en transient fejl ikke handler mod tom state.
- **fetch_history.py** er inkrementel (fuld genhentning mandag/manuel trigger).
- **requirements.txt er pinnet** — opdater bevidst og test via manuel workflow-trigger.
- **Sikkerhed:** hardcode ALDRIG PAT i rutine-prompts. De gamle prompts havde
  en hardcoded PAT (`ghp_a2Am…`) — den SKAL roteres når de PAT-frie prompts i
  `routines/` er sat på triggerne. Rutinerne behøver ingen token; kun GitHub
  Actions bruger `secrets.DASHBOARD_PAT`.

## VIGTIGT: Filstruktur
Al kode ligger **udelukkende på GitHub** — den lokale mappe indeholder kun denne fil.

| Hvad | Hvor |
|------|------|
| GitHub repo | `Poulsen4988/trading-bot-dashboard` |
| Dashboard | https://poulsen4988.github.io/trading-bot-dashboard/ |
| Credentials (.env) | `C:\Users\andre\Mit drev\Claude\.env` |

Læs altid filer via GitHub API. Skriv altid via GitHub API (Contents API med SHA).
Brug DASHBOARD_PAT fra `.env` til autentificering.

---

## Filer
| Fil | Formål |
|-----|--------|
| `watchlist.py` | Eneste kilde til C25-symboler — importer altid herfra |
| `scripts/fetch_prices.py` | Henter priser + nøgletal + earnings-dato + benchmarks → `prices/latest.json` + `prices/benchmarks.json` (GitHub Actions) |
| `news.py` | Henter nyheder → `knowledge/*.json` (GitHub Actions) |
| `screener.py` | Screener alle C25-aktier → `screening/DATO.json` |
| `analyst.py` | Tier-baseret analysegrundlag (deep + scan på alle 25) til analyse-rutinen |
| `decision_prep.py` | Bygger beslutningspakke (portefølje + analyse + ATR-sizing) til handels-rutinen |
| `paper_trader.py` | Læser `decisions/DATO.json`, eksekverer mekanisk, beregner realiseret P&L, opdaterer `data.json` |
| `sync_dashboard.py` | Bygger stocks-data + benchmark-historik + sektoreksponering + pusher dashboard til GitHub Pages |
| `kb_review.py` | Analyserer videnbase for duplikater/stale/low-value items (input til KB Cleanup-rutinen) |
| `github_store.py` | Al GitHub-kommunikation (read/write) — bruges af rutiner |
| `prices/latest.json` | C25-priser — opdateres automatisk af GitHub Actions |
| `prices/benchmarks.json` | Benchmark-priser (^OMXC25, EUNL.DE) — opdateres af GitHub Actions |
| `knowledge/<symbol>.json` | Videnbase per selskab (nyheder) |
| `knowledge_cleanup_reports/DATO.json` | Rapport fra KB Cleanup-rutinen |
| `screening/DATO.json` | Screener-output fra analyse-rutinen |
| `analysis/DATO.json` | Tier-baseret bull/bear-analyse (alle 25) — input til `decision_prep.py` |
| `decisions/DATO.json` | AI-beslutninger — input til `paper_trader.py` |
| `data.json` | Dashboard-data (portfolio, trades, stocks, benchmarks, sector_exposure_pct, latest_decisions) |

## Claude Code Routines
Kører som "Remote" på Anthropic-infrastruktur — PC behøver ikke være tændt.
Repo er automatisk cloned og tilgængeligt i rutinen — scripts kan køres direkte med `python script.py`.

| Navn | Tid (CET) | Trigger ID | Job |
|------|-----------|------------|-----|
| Trading Bot - Analyse | ~09:15 hverdage | `trig_01JipAUsb9pcQqLDVuGX9MzK` | `screener.py` → `screening/DATO.json`, `analyst.py` + tier-baseret bull/bear-analyse på alle 25 → `analysis/DATO.json` |
| Trading Bot - Handel | ~10:45 hverdage | `trig_01MwB6pNkZRedHNBQFA8TmGK` | `decision_prep.py` (med ATR-sizing) → AI beslutter BUY/SELL/HOLD → `decisions/DATO.json` → `paper_trader.py` eksekverer → `data.json` |
| Trading Bot - KB Cleanup | ~10:00 søndag | `trig_01RzzPw66pgDaqSCYemgsncq` | `kb_review.py` → AI gennemgår videnbase, fjerner KUN unødige (duplikater/low-value), skriver `knowledge_cleanup_reports/DATO.json` |
| US Bot - Analyse | ~23:00 hverdage (21:00 UTC) | `trig_015YQjtrbTjDFcfmaBTmRt7R` | `us/analyst.py` → bull/bear på deep-set → `us/analysis/DATO.json` (priser/screening leveres af Action 'US Bot - Data') |
| US Bot - Handel | ~23:30 hverdage (21:30 UTC) | `trig_01NMS3jUTcuEHc6NovxV9r6o` | `us/decision_prep.py` → AI beslutter → `us/decisions/DATO.json` → `us/paper_trader.py` + `us/sync_dashboard.py` → `us/data.json` |
| US Bot - KB Cleanup | ~10:00 søndag (08:00 UTC) | `trig_01J7U6tdkhpWtZYBjyRkXHiN` | `us/kb_review.py` → renser `us/knowledge/*.json`, skriver `us/knowledge_cleanup_reports/DATO.json` |

**Prompts:** de autoritative rutine-prompts ligger i `routines/*.md` (PAT-frie,
offline-tilstand + MCP-push). Ændr prompts dér først, og sæt dem så på
triggerne — se `routines/README.md`.

**Arkitektur:** AI-rutinen træffer ALLE handelsbeslutninger. `paper_trader.py` er dumb executor — ingen hardcodede regler.
**Vigtigt:** Rutinerne bruger `github_store.py` til al GitHub-kommunikation — aldrig git-kommandoer. Kør aldrig `fetch_prices.py` eller `news.py` — GitHub Actions håndterer det.
**Sikkerhed:** Hardcode aldrig PATs i rutine-prompts. Token skal sættes som env-var.

### Sådan læser og redigerer du rutinerne via API

Rutinerne er **ikke** i `~/.claude/scheduled-tasks/` — de er cloud-hosted og tilgås via `RemoteTrigger`-værktøjet.

**Trin 1:** Load værktøjet:
```
ToolSearch → query: "select:RemoteTrigger"
```

**Trin 2:** List alle rutiner (inkl. fuld prompt):
```
RemoteTrigger → action: "list"
```

**Trin 3:** Opdater en rutines prompt:
```
RemoteTrigger → action: "update" → trigger_id: "<ID>" → body: {
  "name": "...",
  "job_config": {
    "ccr": {
      "environment_id": "env_01NKM1bRZAkortPH3EDsuGbw",
      "events": [{
        "data": {
          "message": {"role": "user", "content": "<ny prompt>"},
          "parent_tool_use_id": null,
          "session_id": "",
          "type": "user"
        }
      }]
    }
  }
}
```

**Vigtige IDs** (se `C:\Users\andre\Mit drev\Claude\.env`):
- `ROUTINE_ENV_ID` — skal altid med i body ved update
- `ROUTINE_HANDEL_ID` — Trading Bot - Handel trigger
- `ROUTINE_ANALYSE_ID` — Trading Bot - Analyse trigger
- `ROUTINE_KB_CLEANUP_ID` — Trading Bot - KB Cleanup trigger (søndag)

## GitHub Actions
`fetch_data.yml` kører hver time (07-16 UTC, hverdage):
1. Henter priser + earnings-dato → `prices/latest.json`
2. Henter benchmarks (^OMXC25, EUNL.DE) → `prices/benchmarks.json`
3. Henter nyheder → `knowledge/*.json`
4. Kører `sync_dashboard.py` → opdaterer `data.json` med priser, nyheder, benchmarks, sektoreksponering, dagens beslutninger
5. Committer og pusher til GitHub

Kan trigges manuelt via gh API:
```
gh api -X POST repos/Poulsen4988/trading-bot-dashboard/actions/workflows/fetch_data.yml/dispatches -f ref=main
```

## C25-watchlist
Se `watchlist.py` på GitHub — eneste autoritative kilde.
