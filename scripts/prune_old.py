"""
Sletter gamle daglige mellem-artefakter, så repoet (og rutinens clone) forbliver
lille. Beholder decisions/ (revisionsspor for handler) og prices/history/
(dashboardet henter dem). Sletter kun screening/, analysis/ og
knowledge_cleanup_reports/ ældre end RETAIN_DAYS, baseret på filnavnets dato
(YYYY-MM-DD.json). Idempotent; sletter intet før data er gammelt nok.

Kør fra GitHub Actions før commit. Standard 180 dages opbevaring.
"""
import os
import re
from datetime import date, timedelta

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RETAIN_DAYS = int(os.environ.get("PRUNE_RETAIN_DAYS", "180"))
DIRS = ["screening", "analysis", "knowledge_cleanup_reports"]

cutoff = date.today() - timedelta(days=RETAIN_DAYS)
pat = re.compile(r"(\d{4}-\d{2}-\d{2})\.json$")

removed = 0
for d in DIRS:
    path = os.path.join(SCRIPT_DIR, d)
    if not os.path.isdir(path):
        continue
    for fn in os.listdir(path):
        m = pat.search(fn)
        if not m:
            continue
        try:
            fdate = date.fromisoformat(m.group(1))
        except ValueError:
            continue
        if fdate < cutoff:
            os.remove(os.path.join(path, fn))
            removed += 1

print(f"[prune_old] Slettede {removed} filer ældre end {RETAIN_DAYS} dage (før {cutoff}).")
