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

Optional dashboard sync from journal entries:

```bash
python sync_dashboard.py
```

## Environment variables

Use environment variables rather than hardcoded secrets:

- `GITHUB_TOKEN` or `DASHBOARD_PAT` for writing JSON files back to this repo.
- `ANTHROPIC_API_KEY` for analyst routines.
- `ANTHROPIC_MODEL` optional model override.
- `DASHBOARD_REPO` optional repo override.

## Core files

- `watchlist.py` is the single source of truth for the C25 universe.
- `scripts/fetch_prices.py` fetches prices, fundamentals and technical indicators.
- `screener.py` selects 3-5 stocks for deep analysis.
- `analyst.py` creates bull/bear/head analyst analysis.
- `paper_trader.py` updates the virtual portfolio in `data.json`.
- `data.json` powers the GitHub Pages dashboard.
