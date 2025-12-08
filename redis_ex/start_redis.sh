#!/usr/bin/env bash
set -euo pipefail
PORT="${PORT:-6379}"
CONF_FILE="${CONF_FILE:-$HOME/KVStore/pt_capture/redis.conf}"
REDIS_DIR="$HOME/KVStore/redis"
PIDFILE="$HOME/KVStore/pt_capture/redis.pid"
MAXMEM="${MAXMEM:-}"
EVICTION_POLICY="${EVICTION_POLICY:-allkeys-lru}"
# KEEP_RDB=1 이면 save/appendonly 비활성화를 건너뜀

detect_listener_pid() {
  if command -v ss >/dev/null 2>&1; then
    ss -ltnp 2>/dev/null | awk -v p=":${PORT}$" '$4 ~ p && $1=="LISTEN" {print $NF}' \
      | sed -n 's/.*pid=\([0-9]\+\).*/\1/p' | head -n1 && return
    sudo ss -ltnp 2>/dev/null | awk -v p=":${PORT}$" '$4 ~ p && $1=="LISTEN" {print $NF}' \
      | sed -n 's/.*pid=\([0-9]\+\).*/\1/p' | head -n1 && return
  fi
  if command -v lsof >/dev/null 2>&1; then
    lsof -n -iTCP:${PORT} -sTCP:LISTEN -Fp 2>/dev/null | sed -n 's/^p//p' | head -n1 && return
  fi
  return 1
}

is_pid_listening_on_port() {
  local pid="$1"
  if [[ -z "$pid" ]]; then return 1; fi
  if command -v ss >/dev/null 2>&1; then
    ss -ltnp 2>/dev/null | grep -q "pid=${pid}," && return 0
    sudo ss -ltnp 2>/dev/null | grep -q "pid=${pid}," && return 0
  fi
  if command -v lsof >/dev/null 2>&1; then
    lsof -n -iTCP:${PORT} -sTCP:LISTEN -Fp 2>/dev/null | grep -q "^p${pid}$" && return 0
  fi
  return 1
}

adopt_existing_listener() {
  local pid="$1"
  echo "[*] found existing process listening on ${PORT}, PID=${pid}. Adopting it."
  echo "${pid}" > "$PIDFILE"
}

bash "$HOME/KVStore/pt_capture/build_redis.sh"
mkdir -p "$HOME/KVStore/pt_capture/{redisdata,logs}"

EXISTING_PID="$(detect_listener_pid || true)"
if [[ -n "${EXISTING_PID:-}" ]]; then
  adopt_existing_listener "$EXISTING_PID"
  echo "[*] redis already running (external). Using PID=$(cat "$PIDFILE")"
else
  if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    if is_pid_listening_on_port "$(cat "$PIDFILE")"; then
      echo "[*] redis already running with PID $(cat "$PIDFILE")"
    else
      echo "[*] PID $(cat "$PIDFILE") alive but not listening on ${PORT}. Proceed to start a new one."
    fi
  fi

  EXTRA_OPTS=()
  if [[ "${PORT}" != "6379" ]]; then EXTRA_OPTS+=("--port" "${PORT}"); fi

  echo "[*] starting redis on port ${PORT}"
  "$REDIS_DIR/src/redis-server" "$CONF_FILE" "${EXTRA_OPTS[@]}"

  ok=0
  for i in {1..100}; do
    if "$REDIS_DIR/src/redis-cli" -p "$PORT" ping >/dev/null 2>&1; then
      if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null && \
         is_pid_listening_on_port "$(cat "$PIDFILE")"; then
        ok=1; break
      fi
    fi
    sleep 0.1
  done
  if [[ $ok -ne 1 ]]; then
    echo "[!] redis failed to start cleanly (port ${PORT} in use or no pidfile)."
    echo "[i] Tip: check who uses the port: ss -ltnp | grep :${PORT}"
    exit 1
  fi
  echo "[*] redis started. PID=$(cat "$PIDFILE") LOG=$HOME/KVStore/pt_capture/logs/redis.log"
fi

if [[ -n "$MAXMEM" ]]; then
  echo "[*] applying maxmemory=$MAXMEM policy=$EVICTION_POLICY"
  "$REDIS_DIR/src/redis-cli" -p "$PORT" CONFIG SET maxmemory "$MAXMEM" >/dev/null
  "$REDIS_DIR/src/redis-cli" -p "$PORT" CONFIG SET maxmemory-policy "$EVICTION_POLICY" >/dev/null
fi

# 기본은 퍼시스턴스 비활성화. KEEP_RDB=1 이면 건너뜀(스냅샷 실험용)
if [[ "${KEEP_RDB:-0}" != "1" ]]; then
  "$REDIS_DIR/src/redis-cli" -p "$PORT" CONFIG SET save "" >/dev/null || true
  "$REDIS_DIR/src/redis-cli" -p "$PORT" CONFIG SET appendonly no >/dev/null || true
fi
