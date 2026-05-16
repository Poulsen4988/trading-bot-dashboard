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
| `screener.py` | Screener alle C25-aktier → `screening/DATO.json` |
| `analyst.py` | Printer top-kandidater + priser til stdout |
| `decision_prep.py` | Printer portefølje + analyse til stdout — input til Handel-rutinen |
| `paper_trader.py` | Dumb executor: læser `decisions/DATO.json`, eksekverer mekanisk, opdaterer `data.json` |
| `research.py` | Henter kurser + positioner + kontostatus |
| `trade.py` | Udfører handel: `python trade.py <BUY\|SELL> <UIC> <ANTAL>` |
| `sync_dashboard.py` | Bygger stocks-data + pusher dashboard til GitHub Pages |
| `github_store.py` | Al GitHub-kommunikation (read/write) — bruges af rutiner |
| `prices/latest.json` | C25-priser — opdateres automatisk af GitHub Actions |
| `knowledge/<symbol>.json` | Videnbase per selskab (nyheder, regnskab, analyse) |
| `screening/DATO.json` | Screener-output fra Analyse-rutinen |
| `analysis/DATO.json` | Bull/bear-analyse — input til Handel-rutinen |
| `decisions/DATO.json` | AI's handelsbeslutninger med investment_plan — input til `paper_trader.py` |
| `data.json` | Dashboard-data (portfolio, trades, stocks) |

## Claude Code Routines
Kører som "Remote" på Anthropic-infrastruktur — PC behøver ikke være tændt.
Repo er automatisk cloned og tilgængeligt i rutinen — scripts kan køres direkte med `python script.py`.

| Navn | Tid (CET) | Trigger ID | Job |
|------|-----------|------------|-----|
| Trading Bot - Analyse | ~09:15 | `trig_01JipAUsb9pcQqLDVuGX9MzK` | `screener.py` → `screening/DATO.json`, `analyst.py` + bull/bear-analyse → `analysis/DATO.json` |
| Trading Bot - Handel | ~10:45 | `trig_01MwB6pNkZRedHNBQFA8TmGK` | `decision_prep.py` → AI beslutter BUY/SELL/HOLD → `decisions/DATO.json` → `paper_trader.py` eksekverer → `data.json` |

**Arkitektur:** AI-rutinen træffer ALLE handelsbeslutninger. `paper_trader.py` er dumb executor — ingen hardcodede regler.
**Vigtigt:** Rutinerne bruger `github_store.py` til al GitHub-kommunikation — aldrig git-kommandoer. Kør aldrig `fetch_prices.py` eller `news.py` — GitHub Actions håndterer det.

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

**Vigtige IDs:**
- `environment_id`: `env_01NKM1bRZAkortPH3EDsuGbw` (skal altid med ved update)
- Handel trigger: `trig_01MwB6pNkZRedHNBQFA8TmGK`
- Analyse trigger: `trig_01JipAUsb9pcQqLDVuGX9MzK`

## GitHub Actions
`fetch_data.yml` kører hver time (07-16 UTC, hverdage):
1. Henter priser → `prices/latest.json`
2. Henter nyheder → `knowledge/*.json`
3. Kører `sync_dashboard.py` → opdaterer `data.json` med priser + nyheder
4. Committer og pusher til GitHub

## C25-watchlist
Se `watchlist.py` på GitHub — eneste autoritative kilde.

## Journal-format
```json
{"timestamp": "ISO8601", "action": "BUY|SELL|HOLD", "symbol": "...", "uic": 0, "amount": 0, "price": 0.0, "reason": "..."}
```