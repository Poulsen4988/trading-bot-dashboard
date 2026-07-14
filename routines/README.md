# Rutine-prompts (Claude Code Routines)

Denne mappe indeholder de **autoritative prompts** for de 6 cloud-rutiner.
Prompterne her er PAT-frie og bruger github_stores offline-tilstand
(lokalt klon + pending-manifest + MCP-push til main som sidste trin).

## Hvorfor

Rutine-sandkassen blokerer ofte `api.github.com` (HTTP 403 "GitHub access is
not enabled for this session"). De gamle prompts satte en hardcoded PAT og
læste/skrev via API'et — når proxyen blokerede, returnerede alle reads tom
state og rutinen døde stille (se vagthund-issues #3–#17, 2026-06-30 →
2026-07-10). Den nye arkitektur er deterministisk:

1. **Læs**: alle scripts læser fra det lokale repo-klon (klonet frisk fra
   main ved sessionstart — GitHub Actions har opdateret priser/screening
   inden rutinerne kører).
2. **Skriv**: `github_store.put_json` gemmer lokalt og registrerer filen i
   `.github_store_pending.json`.
3. **Push**: rutinens sidste trin pusher alle pending filer til `main` i ét
   commit via MCP-værktøjet `mcp__github__push_files` (GitHub App —
   den godkendte skrivekanal i sandkassen) og kører derefter
   `python github_store.py --clear`.

Kendt, accepteret race: pusher rutinen `data.json`, overskrives de afledte
felter fra en evt. mellemliggende times-Action — de genopbygges af næste
`sync_dashboard`-kørsel inden for en time. Porteføljefelter ejes stadig kun
af `paper_trader`.

Ingen tokens i prompts. GitHub Actions kører uændret videre med
`secrets.DASHBOARD_PAT` (med token og fungerende API opfører github_store
sig som før).

## Sådan opdateres rutinerne

Rutinerne er cloud-hosted triggers — se CLAUDE.md ("Sådan læser og redigerer
du rutinerne via API"). Fra en lokal session med `RemoteTrigger`-værktøjet:

1. **Merge først denne branch til main** — de nye prompts kræver den nye
   `github_store.py` på main (rutinerne kloner main).
2. For hver rutine: `RemoteTrigger` → action `update` → trigger_id →
   body med `job_config.ccr.events[0].data.message.content` = indholdet af
   den tilsvarende fil her (behold resten af den eksisterende `job_config`
   uændret, inkl. `environment_id`).

| Fil | Rutine | Trigger ID |
|-----|--------|------------|
| `c25_analyse.md` | Trading Bot - Analyse (09:15) | `trig_01JipAUsb9pcQqLDVuGX9MzK` |
| `c25_handel.md` | Trading Bot - Handel (10:45) | `trig_01MwB6pNkZRedHNBQFA8TmGK` |
| `c25_kb_cleanup.md` | Trading Bot - KB Cleanup (søndag) | `trig_01RzzPw66pgDaqSCYemgsncq` |
| `us_analyse.md` | US Bot - Analyse (21:00 UTC) | `trig_015YQjtrbTjDFcfmaBTmRt7R` |
| `us_handel.md` | US Bot - Handel (21:30 UTC) | `trig_01NMS3jUTcuEHc6NovxV9r6o` |
| `us_kb_cleanup.md` | US Bot - KB Cleanup (søndag) | `trig_01J7U6tdkhpWtZYBjyRkXHiN` |

## SIKKERHED — VIGTIGT

De gamle prompts indeholder en hardcoded PAT (`ghp_a2Am…`). Den er også
printet i rutinernes transcripts. **Efter** de nye prompts er sat:

1. Rotér PAT'en på GitHub (Settings → Developer settings → Tokens).
2. Opdater `DASHBOARD_PAT`-secreten i repoets Actions-secrets
   (bruges stadig af `fetch_data.yml`/`us_pipeline.yml`).
3. Opdater `.env` lokalt.

Rutinerne behøver ingen token længere — koden fungerer i øvrigt også selv
om en gammel prompt med død PAT skulle køre (circuit breaker → offline).
