#!/usr/bin/env bash
set -euo pipefail
THREADS="${THREADS:-32}"
RECORDS="${RECORDS:-2000000}"        # 데이터 크기 조절: 2M 레코드(기본) → 수 GB급
FIELDCOUNT="${FIELDCOUNT:-10}"
FIELDLENGTH="${FIELDLENGTH:-100}"    # 값 크기 조절 필요 시 키워드로 수정
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-6379}"
YCSB_DIR="$HOME/KVStore/YCSB"
LOG="$HOME/KVStore/pt_capture/logs/ycsb_load.log"

mkdir -p "$(dirname "$LOG")"
cd "$YCSB_DIR"

echo "[*] YCSB LOAD (workloadd) records=${RECORDS} threads=${THREADS} fieldcount=${FIELDCOUNT} fieldlength=${FIELDLENGTH}" | tee -a "$LOG"
./bin/ycsb load redis -s -P workloads/workloadd \
  -p "redis.host=${HOST}" -p "redis.port=${PORT}" \
  -p "recordcount=${RECORDS}" \
  -p "fieldcount=${FIELDCOUNT}" -p "fieldlength=${FIELDLENGTH}" \
  -threads "${THREADS}" | tee -a "$LOG"
