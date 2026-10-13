#!/usr/bin/env bash
# One-time history load into the AWS dev lake, every balancing authority, in monthly chunks
# (ADR-0005: one year of history). Two lanes run side by side, matching the eia_api pool's 2
# slots: fuel-type-data (the largest route) in one, region-data then interchange-data in the
# other. A chunk that fails is retried once and then reported; rerunning the script is safe
# (raw rows are deduplicated by hash in staging) and skips chunks already marked done.
#   infra/scripts/backfill-aws.sh 2025-10-01 2026-10-13
set -euo pipefail
START="$1"; END="$2"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LOG_DIR="$ROOT/local/data/backfill"; mkdir -p "$LOG_DIR"

months() {  # monthly [start, end) windows covering [START, END)
  python3 - "$START" "$END" <<'PY'
import sys
from datetime import date
s, e = (date.fromisoformat(x) for x in sys.argv[1:3])
cur = s
while cur < e:
    nxt = date(cur.year + cur.month // 12, cur.month % 12 + 1, 1)
    print(cur.isoformat(), min(nxt, e).isoformat())
    cur = nxt
PY
}

lane() {  # lane <route>...: each route, month by month
  for route in "$@"; do
    months | while read -r s e; do
      done_mark="$LOG_DIR/$route.$s.done"
      [ -f "$done_mark" ] && continue
      log="$LOG_DIR/$route.$s.log"
      for attempt in 1 2; do
        if "$ROOT/infra/scripts/extract-aws.sh" eia --route "$route" --start "$s" --end "$e" \
            >"$log" 2>&1; then
          touch "$done_mark"; echo "$(date -u +%H:%M:%S) ok   $route $s"; break
        fi
        echo "$(date -u +%H:%M:%S) FAIL $route $s (attempt $attempt, see $log)"
      done
    done
  done
}

lane fuel-type-data &
lane region-data interchange-data &
wait || true
# Exit status reflects missing chunks only (a lane's last test can be non-zero on success).
missing=0
for route in region-data fuel-type-data interchange-data; do
  while read -r s _; do
    [ -f "$LOG_DIR/$route.$s.done" ] || { echo "missing: $route $s"; missing=$((missing + 1)); }
  done < <(months)
done
echo "backfill finished: $missing chunk(s) missing (rerun to retry them; done chunks are skipped)"
[ "$missing" -eq 0 ]
