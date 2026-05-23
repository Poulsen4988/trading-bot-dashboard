# Trading Bot — Start her (ny session)

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
