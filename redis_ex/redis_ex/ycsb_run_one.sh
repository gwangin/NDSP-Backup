#!/usr/bin/env bash
set -euo pipefail
THREADS="${THREADS:-32}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-6379}"
RECORDS="${RECORDS:-2000000}"
FIELDCOUNT="${FIELDCOUNT:-10}"
FIELDLENGTH="${FIELDLENGTH:-100}"
WORKLOAD="${WORKLOAD:-f}"             # f = 50% read, 50% read-modify-write
RUN_FOR_SECS="${RUN_FOR_SECS:-600}"
OPERATIONCOUNT="${OPERATIONCOUNT:-1000000000}"
YCSB_DIR="$HOME/KVStore/YCSB"
LOG="$HOME/KVStore/pt_capture/logs/ycsb_run.log"

mkdir -p "$(dirname "$LOG")"
cd "$YCSB_DIR"

wfile="workloads/workload${WORKLOAD}"
if [[ ! -f "$wfile" ]]; then
  echo "[!] workload file not found: $wfile" | tee -a "$LOG"
  exit 1
fi

echo "[*] YCSB RUN workload${WORKLOAD} for ${RUN_FOR_SECS}s (PT capture ON) records=${RECORDS} fieldcount=${FIELDCOUNT} fieldlength=${FIELDLENGTH}" | tee -a "$LOG"
./bin/ycsb run redis -s -P "$wfile" \
  -p "redis.host=${HOST}" -p "redis.port=${PORT}" \
  -p "recordcount=${RECORDS}" \
  -p "fieldcount=${FIELDCOUNT}" -p "fieldlength=${FIELDLENGTH}" \
  -p "operationcount=${OPERATIONCOUNT}" \
  -p "maxexecutiontime=${RUN_FOR_SECS}" \
  -threads "${THREADS}" | tee -a "$LOG"
