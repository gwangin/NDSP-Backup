#!/usr/bin/env bash
set -euo pipefail
if [[ $# -lt 1 ]]; then
  echo "usage: sudo $0 <PID> [interval_sec=5]"; exit 1
fi
PID="$1"; INT="${2:-5}"
OUTDIR="$(cd "$(dirname "$0")" && pwd)/snapshots"
BASED="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$OUTDIR"

USE_MAPS="${USE_MAPS:-0}"

echo "[*] capturing pagemap PID=$PID every ${INT}s -> $OUTDIR (maps=${USE_MAPS})"
while kill -0 "$PID" 2>/dev/null; do
  ts=$(date +%s)
  if [[ "$USE_MAPS" == "1" ]]; then
    /usr/bin/env python3 "$BASED/snap_pagetable.py" --pid "$PID" --out "${OUTDIR}/pt_${ts}.csv.gz" --maps "${OUTDIR}/maps_${ts}.txt"
  else
    /usr/bin/env python3 "$BASED/snap_pagetable.py" --pid "$PID" --out "${OUTDIR}/pt_${ts}.csv.gz"
  fi
  echo "[*] snapshot ${ts} done"

  # --> 실시간 diff + RSS 줄을 반드시 남김
  if ! /usr/bin/env python3 -u "$BASED/append_last_diff.py"; then
    echo "[live] append_last_diff failed; will retry next tick"
  fi

  sleep "$INT"
done
echo "[*] target ended"
