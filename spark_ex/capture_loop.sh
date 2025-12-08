#!/usr/bin/env bash
PID="$1"; SNAPDIR="$2"; INT="${3:-5}"; LOGFILE="${4:-$HOME/spark/graph_snapshot/log/pt_changes.log}"
BASE="$(cd "$(dirname "$0")"/.. && pwd)"
mkdir -p "$SNAPDIR" "$(dirname "$LOGFILE")"

read_rss_kb() {
  local pid="$1"
  if [[ -r "/proc/$pid/smaps_rollup" ]]; then
    awk '/^Rss:/{print $2;exit}' "/proc/$pid/smaps_rollup" 2>/dev/null || echo 0
  elif [[ -r "/proc/$pid/status" ]]; then
    awk '/^VmRSS:/{print $2;exit}' "/proc/$pid/status" 2>/dev/null || echo 0
  elif [[ -r "/proc/$pid/statm" ]]; then
    local pages=$(awk '{print $2}' "/proc/$pid/statm" 2>/dev/null)
    local psize=$(( $(getconf PAGESIZE) / 1024 ))
    echo $(( pages * psize ))
  else
    echo 0
  fi
}

make_empty_snap_gz() { printf "vpn_hex,status,pfn\n" | gzip -c > "$1"; }

echo "[] capturing PID=$PID every ${INT}s → $SNAPDIR" >&2
prev=""
while kill -0 "$PID" 2>/dev/null; do
  ts=$(date +%s)
  curr="$SNAPDIR/pt_${ts}.csv.gz"
  python3 "$BASE/bin/snap_pagetable.py" --pid "$PID" --out "$curr" || { sleep "$INT"; continue; }
  rss_kb="$(read_rss_kb "$PID" || echo 0)"
  if [[ -n "$prev" && -s "$prev" ]]; then
    python3 "$BASE/bin/append_change_log.py" --prev "$prev" --curr "$curr" --pid "$PID" --log "$LOGFILE" --rss-kb "$rss_kb" || true
  fi
  prev="$curr"
  sleep "$INT" || true
done

if [[ -n "$prev" && -s "$prev" ]]; then
  final_empty="$SNAPDIR/pt_final_empty.csv.gz"
  make_empty_snap_gz "$final_empty"
  python3 "$BASE/bin/append_change_log.py" --prev "$prev" --curr "$final_empty" --pid "$PID" --log "$LOGFILE" --rss-kb 0 || true
fi

echo "[] target ended" >&2
