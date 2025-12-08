#!/usr/bin/env bash
set -euo pipefail
PORT="${PORT:-6379}"
CAP_INTERVAL="${CAP_INTERVAL:-5}"          # pagemap 스냅샷 간격(초)
ENABLE_COW="${ENABLE_COW:-1}"              # 기본: RDB 스냅샷으로 COW 유도
BGSAVE_EVERY="${BGSAVE_EVERY:-10}"         # BGSAVE 주기(초) — 일반 처리와 겹치게 짧게

BASE="$HOME/KVStore/pt_capture"
REDIS_CLI="$HOME/KVStore/redis/src/redis-cli"

# Redis 기동 (RDB 사용할 거라 KEEP_RDB=1로)
KEEP_RDB=${KEEP_RDB:-1} bash "$BASE/start_redis.sh"

if [[ "$ENABLE_COW" == "1" ]]; then
  echo "[*] enabling periodic RDB saves to trigger COW (save 10 1, BGSAVE every ${BGSAVE_EVERY}s)"
  "$REDIS_CLI" -p "$PORT" CONFIG SET save "10 1" >/dev/null || true
  ( while true; do "$REDIS_CLI" -p "$PORT" BGSAVE >/dev/null 2>&1; sleep "${BGSAVE_EVERY}"; done ) &
  echo $! > "$BASE/bgsave_loop.pid"
fi

# Load 단계 (캡처 없음) — 데이터는 충분히 크게 유지(기본 2M 레코드)
bash "$BASE/ycsb_load.sh"

# 캡처 시작(5s 기본)
if ! sudo -v; then
  echo "[!] sudo authentication failed. Cannot capture pagemap."; exit 1
fi
bash "$BASE/start_capture.sh" "$CAP_INTERVAL"

# Run 단계 — workload f(SET50:GET50)로 COW와 겹치게
WORKLOAD="${WORKLOAD:-f}" bash "$BASE/ycsb_run_one.sh"

# 캡처 정리
bash "$BASE/stop_capture.sh"

# BGSAVE 루프 종료
if [[ -f "$BASE/bgsave_loop.pid" ]]; then
  kill "$(cat "$BASE/bgsave_loop.pid")" 2>/dev/null || true
  rm -f "$BASE/bgsave_loop.pid"
fi

bash "$BASE/stop_redis.sh"

echo "[*] done."
echo "snapshots: $BASE/snapshots"
echo "diffs:     $BASE/diffs"
echo "capture log: $BASE/logs/capture.log"
