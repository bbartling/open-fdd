#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VENV="${OPENFDD_VENV:-env}"
BRIDGE_PORT="${OPENFDD_BRIDGE_PORT:-8765}"
MCP_PORT="${OPENFDD_MCP_PORT:-8090}"
DASH_PORT="${OPENFDD_DASH_PORT:-5173}"

SKIP_PIP_INSTALL="${OPENFDD_SKIP_PIP_INSTALL:-0}"
WITH_MCP="${OPENFDD_WITH_MCP:-1}"
WITH_FDD_RUNNER="${OPENFDD_WITH_FDD_RUNNER:-0}"

LOG_DIR="$ROOT/.dev-logs"
PID_DIR="$ROOT/.dev-pids"
mkdir -p "$LOG_DIR" "$PID_DIR"

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1"
    exit 1
  }
}

check_stack_health() {
  local url="http://127.0.0.1:${BRIDGE_PORT}/health/stack"
  local body
  local status

  echo
  echo "Checking stack health: ${url}"

  body="$(curl -sS "$url" || true)"

  if [[ -z "$body" ]]; then
    echo "WARN: /health/stack returned no response."
    echo "      Bridge may still be starting, or the route is not mounted in this checkout."
    return 0
  fi

  if ! echo "$body" | jq empty >/dev/null 2>&1; then
    echo "WARN: /health/stack did not return valid JSON."
    echo "Raw response:"
    echo "$body"
    return 0
  fi

  if ! echo "$body" | jq -e '.services and (.services | type == "array")' >/dev/null 2>&1; then
    echo "WARN: /health/stack JSON did not include .services[]."
    echo "Raw response:"
    echo "$body" | jq .
    echo
    echo "This usually means one of:"
    echo "  - /health/stack is not available in this branch/check-out"
    echo "  - the bridge app mounted a different route set"
    echo "  - the bridge returned an error JSON instead of stack health"
    return 0
  fi

  status="$(echo "$body" | jq -r '.overall // .status // "unknown"')"

  echo "Stack overall: ${status}"
  echo "$body" | jq -r '
    .services[]
    | "  - \(.label // .id): \(.status // "unknown") — \(.detail // "")"
  '

  echo
  echo "Compact service status:"
  echo "$body" | jq '.services[] | {id,label,status,configured,detail}'
}

stop_pid_file() {
  local file="$1"
  [[ -f "$file" ]] || return 0

  local pid
  pid="$(cat "$file" 2>/dev/null || true)"

  if [[ -n "${pid:-}" ]] && kill -0 "$pid" 2>/dev/null; then
    echo "Stopping PID from $file: $pid"
    kill "$pid" 2>/dev/null || true
  fi

  rm -f "$file"
}

stop_known_patterns() {
  pkill -f "uvicorn openfdd_bridge.main:app" 2>/dev/null || true
  pkill -f "uvicorn mcp_server.asgi:create_app" 2>/dev/null || true
  pkill -f "openfdd_bridge.fdd_runner" 2>/dev/null || true
  pkill -f "npm run dev -- --host 127.0.0.1 --port ${DASH_PORT}" 2>/dev/null || true
  pkill -f "vite.*--host 127.0.0.1.*--port ${DASH_PORT}" 2>/dev/null || true
  pkill -f "node.*vite.*${DASH_PORT}" 2>/dev/null || true
}

kill_openfdd_port_owner() {
  local port="$1"

  local pids
  pids="$(ss -ltnp 2>/dev/null \
    | awk -v port=":${port}" '$4 ~ port {print $0}' \
    | sed -n 's/.*pid=\([0-9]\+\).*/\1/p' \
    | sort -u)"

  for pid in $pids; do
    local cmd
    cmd="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"

    if [[ "$cmd" == *openfdd_bridge.main:app* ]] \
      || [[ "$cmd" == *mcp_server.asgi:create_app* ]] \
      || [[ "$cmd" == *openfdd_bridge.fdd_runner* ]] \
      || [[ "$cmd" == *vite* ]] \
      || [[ "$cmd" == *"npm run dev"* ]]; then
      echo "Killing Open-FDD dev PID $pid on port $port:"
      echo "  $cmd"
      kill "$pid" 2>/dev/null || true
    else
      echo "Port $port is used by non-Open-FDD process PID $pid:"
      echo "  $cmd"
      echo "Not killing it automatically."
    fi
  done
}

stop_old_local_dev() {
  echo "=== existing listeners ==="
  ss -ltnp | grep -E ":${BRIDGE_PORT}|:${MCP_PORT}|:${DASH_PORT}" || true
  echo

  echo "=== stopping old Open-FDD local dev processes ==="

  stop_pid_file "$PID_DIR/bridge.pid"
  stop_pid_file "$PID_DIR/mcp.pid"
  stop_pid_file "$PID_DIR/dashboard.pid"
  stop_pid_file "$PID_DIR/fdd_runner.pid"

  sleep 1
  stop_known_patterns
  sleep 1

  kill_openfdd_port_owner "$BRIDGE_PORT"
  kill_openfdd_port_owner "$MCP_PORT"
  kill_openfdd_port_owner "$DASH_PORT"

  sleep 1

  echo "=== listeners after cleanup ==="
  ss -ltnp | grep -E ":${BRIDGE_PORT}|:${MCP_PORT}|:${DASH_PORT}" || echo "ports are free"
  echo
}

wait_http() {
  local url="$1"
  local name="$2"
  local tries="${3:-40}"

  for _ in $(seq 1 "$tries"); do
    if curl -fsS "$url" >/tmp/openfdd-dev-health.json 2>/dev/null; then
      echo "$name is up: $url"
      cat /tmp/openfdd-dev-health.json || true
      echo
      return 0
    fi
    sleep 1
  done

  echo "$name did not become healthy: $url"
  return 1
}

cleanup() {
  echo
  echo "=== stopping local dev processes started by this script ==="

  stop_pid_file "$PID_DIR/bridge.pid"
  stop_pid_file "$PID_DIR/mcp.pid"
  stop_pid_file "$PID_DIR/dashboard.pid"
  stop_pid_file "$PID_DIR/fdd_runner.pid"

  stop_known_patterns
}
trap cleanup EXIT INT TERM

need_cmd curl
need_cmd jq
need_cmd ss
need_cmd python
need_cmd npm

if [[ ! -f "$VENV/bin/activate" ]]; then
  echo "Missing venv: $ROOT/$VENV"
  echo "Create it first, or set OPENFDD_VENV=.venv"
  exit 1
fi

source "$VENV/bin/activate"

if [[ ! -f workspace/auth.env.local ]]; then
  echo "Missing workspace/auth.env.local"
  echo "Run bootstrap or create local auth first."
  exit 1
fi

set -a
. ./workspace/auth.env.local
set +a

export OFDD_BRIDGE_HOST=127.0.0.1
export PYTHONPATH="$ROOT/workspace/api:$ROOT/workspace:$ROOT:${PYTHONPATH:-}"

echo "=== Open-FDD local dev ==="
echo "root:       $ROOT"
echo "venv:       $VENV"
echo "bridge:     http://127.0.0.1:${BRIDGE_PORT}"
echo "mcp:        http://127.0.0.1:${MCP_PORT}"
echo "dashboard:  http://127.0.0.1:${DASH_PORT}"
echo "logs:       $LOG_DIR"
echo

stop_old_local_dev

if [[ "$SKIP_PIP_INSTALL" != "1" ]]; then
  echo "=== installing/checking Python dev deps ==="
  python -m pip install -q -e ".[dev,bridge]"
else
  echo "=== skipping pip install because OPENFDD_SKIP_PIP_INSTALL=1 ==="
fi
echo

echo "=== import checks ==="
python - <<'PY'
import openfdd_bridge.main
print("openfdd_bridge.main import OK")

import mcp_server.asgi
print("mcp_server.asgi import OK")
PY
echo

if [[ "$WITH_MCP" == "1" ]]; then
  echo "=== starting MCP sidecar on ${MCP_PORT} ==="
  python -m uvicorn mcp_server.asgi:create_app \
    --factory \
    --app-dir workspace \
    --host 127.0.0.1 \
    --port "$MCP_PORT" \
    --reload \
    --reload-dir workspace/mcp_server \
    > "$LOG_DIR/mcp.log" 2>&1 &
  echo $! > "$PID_DIR/mcp.pid"
else
  echo "=== MCP disabled: OPENFDD_WITH_MCP=0 ==="
fi

echo "=== starting bridge API on ${BRIDGE_PORT} ==="
python -m uvicorn openfdd_bridge.main:app \
  --app-dir workspace/api \
  --host 127.0.0.1 \
  --port "$BRIDGE_PORT" \
  --reload \
  --reload-dir workspace/api \
  --reload-dir open_fdd \
  --reload-dir bacnet_toolshed \
  > "$LOG_DIR/bridge.log" 2>&1 &
echo $! > "$PID_DIR/bridge.pid"

echo "=== waiting for bridge ==="
if ! wait_http "http://127.0.0.1:${BRIDGE_PORT}/health" "bridge" 45; then
  echo
  echo "=== bridge log ==="
  tail -160 "$LOG_DIR/bridge.log" || true
  exit 1
fi

echo "=== checking BACnet override routes ==="
curl -fsS "http://127.0.0.1:${BRIDGE_PORT}/openapi.json" \
  | jq -r '.paths | keys[]' \
  | grep -Ei 'overrides/summary|bacnet/override' \
  | sort || true
echo

if [[ "$WITH_FDD_RUNNER" == "1" ]]; then
  echo "=== starting FDD runner loop ==="
  python -m openfdd_bridge.fdd_runner \
    --loop \
    --interval-minutes "${OPENFDD_FDD_INTERVAL_MINUTES:-60}" \
    --lookback-hours "${OPENFDD_FDD_LOOKBACK_HOURS:-1}" \
    > "$LOG_DIR/fdd_runner.log" 2>&1 &
  echo $! > "$PID_DIR/fdd_runner.pid"
else
  echo "=== FDD runner disabled: OPENFDD_WITH_FDD_RUNNER=0 ==="
fi
echo

echo "=== installing/checking dashboard deps ==="
cd "$ROOT/workspace/dashboard"

if [[ ! -d node_modules ]]; then
  npm install
fi

echo "=== starting dashboard on ${DASH_PORT} ==="
npm run dev -- --host 127.0.0.1 --port "$DASH_PORT" \
  > "$LOG_DIR/dashboard.log" 2>&1 &
echo $! > "$PID_DIR/dashboard.pid"

cd "$ROOT"

echo "=== waiting for dashboard ==="
for i in $(seq 1 40); do
  if curl -fsS "http://127.0.0.1:${DASH_PORT}" >/dev/null 2>&1; then
    echo "dashboard is up: http://127.0.0.1:${DASH_PORT}"
    break
  fi

  sleep 1

  if [[ "$i" == "40" ]]; then
    echo "Dashboard did not become healthy. Last dashboard log:"
    tail -120 "$LOG_DIR/dashboard.log" || true
    exit 1
  fi
done

echo
echo "=== local dev is running ==="
echo "Dashboard: http://127.0.0.1:${DASH_PORT}"
echo "Bridge:    http://127.0.0.1:${BRIDGE_PORT}/health"
echo "MCP:       http://127.0.0.1:${MCP_PORT}"
echo
echo "Logs:"
echo "  bridge:    $LOG_DIR/bridge.log"
echo "  dashboard: $LOG_DIR/dashboard.log"
if [[ "$WITH_MCP" == "1" ]]; then
  echo "  mcp:       $LOG_DIR/mcp.log"
fi
if [[ "$WITH_FDD_RUNNER" == "1" ]]; then
  echo "  fdd:       $LOG_DIR/fdd_runner.log"
fi
echo
echo "Press Ctrl+C to stop everything."
echo

log_files=("$LOG_DIR/bridge.log" "$LOG_DIR/dashboard.log")
if [[ "$WITH_MCP" == "1" ]]; then
  log_files+=("$LOG_DIR/mcp.log")
fi
if [[ "$WITH_FDD_RUNNER" == "1" ]]; then
  log_files+=("$LOG_DIR/fdd_runner.log")
fi

wait_for_bridge_health() {
  local url="http://127.0.0.1:${BRIDGE_PORT}/health"

  echo
  echo "Waiting for bridge health: ${url}"

  for i in {1..30}; do
    if curl -fsS "$url" >/tmp/openfdd_bridge_health.json 2>/dev/null; then
      echo "Bridge health OK:"
      jq . /tmp/openfdd_bridge_health.json || cat /tmp/openfdd_bridge_health.json
      return 0
    fi

    sleep 1
  done

  echo "ERROR: bridge did not become healthy at ${url}"
  return 1
}

tail -n +1 -f "${log_files[@]}"
