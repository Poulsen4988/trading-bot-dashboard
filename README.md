# trading-bot-dashboard

AI paper-trading dashboard for OMX Copenhagen/C25.

Dashboard: https://poulsen4988.github.io/trading-bot-dashboard/

## Current flow

This project is now a virtual paper-trading setup. It does not place live orders and has no Saxo integration.

Run the routines in this order:

```bash
python screener.py
python analyst.py
python paper_trader.py
```

Important: `analyst.py` is only a data-prep helper. It does not call Anthropic API. The Claude Routine itself performs the deep analysis and writes `analysis/YYYY-MM-DD.json`.

Optional dashboard sync from journal entries:

```bash
python sync_dashboard.py
```

## Secrets

Do not hardcode GitHub PATs, API keys or OAuth tokens in prompts or code.

When running inside Claude Routines with the repository selected, the routines should update files in the repo and then use `git add`, `git commit`, and `git push`.

## Core files

- `watchlist.py` is the single source of truth for the C25 universe.
- `scripts/fetch_prices.py` fetches prices, fundamentals and technical indicators.
- `screener.py` selects 3-5 stocks for deep analysis.
- `analyst.py` prints the selected analysis input for the Claude Routine.
- `paper_trader.py` updates the virtual portfolio in `data.json`.
- `data.json` powers the GitHub Pages dashboard.
