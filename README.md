# trading-bot-dashboard

AI paper-trading dashboard for OMX Copenhagen/C25.

Dashboard: https://poulsen4988.github.io/trading-bot-dashboard/

## Flow

Virtuel papirhandel. Ingen live-ordrer, ingen Saxo-integration.

To Claude Code Routines kører dagligt på Anthropic-infrastruktur:

1. **Analyse (~09:15 CET)** — `screener.py` udvælger 3-5 aktier → `screening/DATO.json`.
   `analyst.py` printer analysegrundlag; rutinen laver bull/bear-analyse → `analysis/DATO.json`.
2. **Handel (~10:45 CET)** — `decision_prep.py` bygger beslutningspakke; rutinen træffer
   BUY/SELL/HOLD → `decisions/DATO.json`; `paper_trader.py` eksekverer → `data.json`.

GitHub Actions (`fetch_data.yml`) henter priser + nyheder hver time og kører `sync_dashboard.py`.

## GitHub I/O

Al læsning og skrivning til repoet sker via `github_store.py` (Contents API med SHA).
Rutinerne bruger **aldrig** git-kommandoer. Token læses fra env-var `DASHBOARD_PAT` /
`GITHUB_TOKEN` — må aldrig hardcodes i kode eller rutine-prompts.

## Kernefiler

- `watchlist.py` — eneste kilde til C25-universet.
- `scripts/fetch_prices.py` — henter priser + fundamentale nøgletal via yfinance.
- `news.py` — henter nyheder til `knowledge/`.
- `screener.py` — score-model, vælger 3-5 aktier til dybdeanalyse.
- `analyst.py` — printer analysegrundlag til handels-rutinen.
- `decision_prep.py` — bygger beslutningspakke (portefølje + analyse).
- `paper_trader.py` — eksekverer rutinens beslutninger mod `data.json`.
- `sync_dashboard.py` — bygger dashboard-data og pusher til GitHub Pages.
- `github_store.py` — al GitHub-kommunikation.
- `data.json` — driver dashboardet.

## Secrets

Hardcode aldrig GitHub PATs, API-nøgler eller OAuth-tokens i prompts eller kode.
