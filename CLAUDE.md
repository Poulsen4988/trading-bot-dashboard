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
| `scripts/fetch_prices.py` | Henter live C25-kurser via yfinance → `prices/latest.json` |
| `news.py` | Henter nyheder via yfinance → gemmer i `knowledge/<symbol>.json` |
| `research.py` | Henter kurser + positioner + kontostatus |
| `trade.py` | Udfører handel: `python trade.py <BUY\|SELL> <UIC> <ANTAL>` |
| `sync_dashboard.py` | Bygger stocks-data + pusher dashboard til GitHub Pages |
| `watchlist.py` | Eneste kilde til C25-symboler — importer altid herfra |
| `knowledge/<symbol>.json` | Videnbase per selskab (nyheder, regnskab, analyse) |
| `prices/latest.json` | Seneste C25-priser — opdateres af fetch_data workflow (hver time) |
| `screening/YYYY-MM-DD.json` | Screener-output — top-kandidater med bull/bear-tese |
| `data.json` | Dashboard-data (portfolio, trades, stocks) |

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
