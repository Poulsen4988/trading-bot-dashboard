# Trading Bot — Paper Trading Routine

## Formål
Du driver en virtuel paper-trading bot for danske OMX Copenhagen/C25-aktier.

Der handles **ikke** med rigtige penge. Der bruges **ingen Saxo-integration**, ingen live order execution og ingen hardcodede tokens i kode eller prompts.

Dashboard:
https://poulsen4988.github.io/trading-bot-dashboard/

## Overordnet flow

Flowet består af tre hovedroller, der kan køres fra Claude routines eller lokalt:

1. **Screener Agent** — `python screener.py`
   - Kører `scripts/fetch_prices.py`.
   - Henter friske C25-priser via yfinance.
   - Beregner tekniske indikatorer som RSI, MACD, Bollinger Bands, SMA50/SMA200, ATR og stochastic.
   - Udvælger 3-5 mest interessante aktier.
   - Gemmer resultat i `screening/YYYY-MM-DD.json`.

2. **Deep Analyst Agent** — `python analyst.py`
   - Læser dagens screening.
   - Læser `prices/latest.json`.
   - Laver bull-, bear- og head-analyst analyse for hver valgt aktie.
   - Gemmer resultat i `analysis/YYYY-MM-DD.json`.

3. **Trader Agent** — `python paper_trader.py`
   - Læser dagens analyse og `data.json`.
   - Udfører kun virtuelle handler i dashboard-data.
   - Opdaterer `data.json` med positioner, trades og historik.

## Credentials

Brug environment variables, aldrig hardcodede tokens:

- `GITHUB_TOKEN` eller `DASHBOARD_PAT` — bruges til at skrive JSON-filer til repoet.
- `ANTHROPIC_API_KEY` — bruges af analyst/bot scripts.
- `ANTHROPIC_MODEL` — valgfri model override.
- `DASHBOARD_REPO` — valgfrit repo override, default `Poulsen4988/trading-bot-dashboard`.

Hvis GitHub-token mangler, gemmer scripts relevante JSON-filer lokalt.

## Risikoregler for paper trading

Reglerne skal være konservative, men ikke mekaniske tvangssalg:

- Ingen fast grænse på 3 åbne positioner.
- Ingen automatisk tvangssalg ved -5%.
- En ny BUY-idé bør som udgangspunkt ikke overstige ca. 25% af porteføljen.
- Der laves maksimalt én ny BUY pr. dag i `paper_trader.py`.
- BUY kræver normalt `verdict=BULL` og `confidence>=65`.
- SELL kræver normalt `verdict=BEAR` og `confidence>=60`, eller at en position er markant svækket og ikke længere har BULL thesis.
- Positioner omkring -8% eller dårligere skal gennem risikoreview; salg sker kun hvis thesis ikke længere støtter positionen.
- HOLD er altid gyldigt ved usikkerhed eller manglende data.

## Én sand kilde

`watchlist.py` er eneste sandhed for C25-univers, selskabsnavne, Yahoo tickers, Saxo-symboltekst og eventuelle UIC-felter.

Andre scripts må ikke have separate hardcodede C25-lister.

## Centrale filer

- `watchlist.py` — C25-univers og metadata.
- `scripts/fetch_prices.py` — pris-, fundamental- og teknisk data.
- `screener.py` — udvælger 3-5 aktier til dybanalyse.
- `analyst.py` — bull/bear/head analyst analyse.
- `paper_trader.py` — virtuel porteføljeopdatering.
- `github_store.py` — læs/skriv JSON til GitHub eller lokalt fallback.
- `risk_manager.py` — deterministisk normalisering og risikoannotering for analysebeslutninger.
- `research.py` — kompakt markeds-/porteføljeoutput.
- `sync_dashboard.py` — synkroniserer journal til `data.json`.
- `data.json` — dashboardets aktuelle portefølje, historik og trades.
- `prices/latest.json` — seneste prisdata.
- `screening/YYYY-MM-DD.json` — screener-output.
- `analysis/YYYY-MM-DD.json` — dybanalyser.

## Forbudt

- Hardcode aldrig PATs, API keys eller OAuth tokens.
- Genindfør ikke Saxo-order execution uden en separat, bevidst beslutning.
- Tilføj ikke GitHub Actions-workflows, medmindre det specifikt ønskes.
- Duplikér ikke C25-listen udenfor `watchlist.py`.
