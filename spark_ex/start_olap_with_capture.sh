#!/usr/bin/env bash
set -euo pipefail
MEM="${1:-8g}"
HOLD="${2:-0}"          # 호환용, 미사용
INTERVAL="${3:-5}"
WORK_SECS="${4:-3600}"  # 기본 1시간

BASE="$HOME/spark/olap_snapshot_pt"
SNAPDIR="$BASE/snapshot"
LOGFILE="$BASE/log/pt_changes.log"
PIDDIR="$BASE/pids"
APP="$BASE/bin/olap_app.py"
APPNAME="OLAP-Filter-SnapshotPT"

source "$BASE/bin/env.sh"
mkdir -p "$SNAPDIR" "$PIDDIR" "$(dirname "$LOGFILE")"
: > "$PIDDIR/olap_driver_java.pid" || true

echo "[*] Using SPARK_HOME=$SPARK_HOME"
"$SPARK_HOME/bin/spark-submit" --version || true

if ! sudo -n true 2>/dev/null; then
  echo "[*] sudo password may be required for /proc/<PID>/pagemap..."
  sudo -v
fi

# 앱 기동
SPARK_PID_DIR="$PIDDIR" WORK_SECS="$WORK_SECS" \
  "$SPARK_HOME/bin/spark-submit" --master local[*] --driver-memory "$MEM" "$APP" \
  >"$BASE/log/app.stdout" 2>"$BASE/log/app.stderr" & APP_BG=$!

# 드라이버 PID 탐색
deadline=$(( $(date +%s) + 180 )); DRV=""
while [[ -z "$DRV" && $(date +%s) -le $deadline ]]; do
  if [[ -s "$PIDDIR/olap_driver_java.pid" ]]; then
    cand="$(tr -d '[:space:]' < "$PIDDIR/olap_driver_java.pid" 2>/dev/null || true)"
    [[ "$cand" =~ ^[0-9]+$ ]] && [[ -d "/proc/$cand" ]] && DRV="$cand" && break
  fi
  if command -v jps >/dev/null 2>&1; then
    cand="$(jps -l | awk '/org\.apache\.spark\.deploy\.SparkSubmit/{print $1; exit}')"
    [[ "$cand" =~ ^[0-9]+$ ]] && [[ -d "/proc/$cand" ]] && DRV="$cand" && break
  fi
  cand="$(ps -eo pid,cmd --cols 500 | awk -v pat="$APPNAME" 'tolower($0) ~ /java/ && tolower($0) ~ /org\.apache\.spark\.deploy\.sparksubmit/ && index($0, pat) {print $1; exit}')"
  [[ "$cand" =~ ^[0-9]+$ ]] && [[ -d "/proc/$cand" ]] && DRV="$cand" && break
  sleep 0.3
done

if [[ -z "$DRV" ]]; then
  echo "ERROR: driver PID not found"
  echo "== tail app logs =="
  tail -n 80 "$BASE/log/app.stderr" || true
  tail -n 40 "$BASE/log/app.stdout" || true
  wait "$APP_BG" || true
  exit 1
fi

echo "$DRV" > "$PIDDIR/target.pid"
echo "[*] target JVM PID: $DRV"

# 캡처 루프 시작
sudo bash "$BASE/bin/capture_loop.sh" "$DRV" "$SNAPDIR" "$INTERVAL" "$LOGFILE" \
  >>"$BASE/log/capture.stdout" 2>>"$BASE/log/capture.stderr" & CAP_BG=$!
echo "$CAP_BG" > "$PIDDIR/capture_loop.bgpid"

# 앱 종료 대기
wait "$APP_BG" || true

# 캡처 정리
if [[ -f "$PIDDIR/capture_loop.bgpid" ]] && kill -0 "$(cat "$PIDDIR/capture_loop.bgpid")" 2>/dev/null; then
  kill "$(cat "$PIDDIR/capture_loop.bgpid")" 2>/dev/null || true
fi

echo "[*] done. snapshots: $SNAPDIR"
echo "[*] log: $LOGFILE"
