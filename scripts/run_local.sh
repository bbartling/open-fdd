#!/usr/bin/env bash
# Local edge-like stack: compiled React + bridge on 0.0.0.0:8765 (default).
#
#   ./scripts/run_local.sh start          # build if needed, serve SPA+API
#   ./scripts/run_local.sh start --dev    # also run Vite dev on :5173
#   ./scripts/run_local.sh stop
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PID_DIR="${ROOT}/workspace/.local-run"
BRIDGE_PID="${PID_DIR}/bridge.pid"
UI_PID="${PID_DIR}/ui.pid"
BRIDGE_LOG="${PID_DIR}/bridge.log"
UI_LOG="${PID_DIR}/ui.log"

export OPENFDD_REPO_ROOT="$ROOT"
export OPENFDD_WORKSPACE_DIR="${ROOT}/workspace"
export OFDD_DESKTOP_DATA_DIR="${ROOT}/workspace/data"
export PYTHONPATH="$ROOT"
export OFDD_BRIDGE_HOST="${OFDD_BRIDGE_HOST:-0.0.0.0}"
export OFDD_BRIDGE_PORT="${OFDD_BRIDGE_PORT:-8765}"
export OFDD_CORS_ALLOW_PRIVATE_LAN="${OFDD_CORS_ALLOW_PRIVATE_LAN:-1}"

if [[ -f "${ROOT}/workspace/auth.env.local" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${ROOT}/workspace/auth.env.local"
  set +a
  echo "Loaded workspace/auth.env.local (auth enabled if OFDD_AUTH_SECRET set)"
fi

VENV="${ROOT}/.venv"
DEV_UI=false
CMD="${1:-start}"
shift || true
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dev) DEV_UI=true; shift ;;
    *) shift ;;
  esac
done

ensure_build() {
  if [[ ! -f workspace/api/static/app/index.html ]]; then
    ./scripts/build_and_test.sh
  fi
}

start_bridge() {
  mkdir -p "$PID_DIR" workspace/data workspace/bacnet/commissioning workspace/bacnet/polls
  if [[ -f "$BRIDGE_PID" ]] && kill -0 "$(cat "$BRIDGE_PID")" 2>/dev/null; then
    echo "Restarting bridge (pick up code/env changes)…"
    stop_one "$BRIDGE_PID" "bridge"
  fi
  ensure_build
  "${VENV}/bin/pip" install -q -e ".[dev,engine]" -r workspace/api/requirements.txt
  nohup "${VENV}/bin/uvicorn" openfdd_bridge.main:app \
    --app-dir workspace/api \
    --host "$OFDD_BRIDGE_HOST" --port "$OFDD_BRIDGE_PORT" \
    >"$BRIDGE_LOG" 2>&1 &
  echo $! >"$BRIDGE_PID"
  echo "Bridge pid=$(cat "$BRIDGE_PID") → http://${OFDD_BRIDGE_HOST}:${OFDD_BRIDGE_PORT}"
}

start_commission_agent() {
  if pgrep -f "bacnet_toolshed.commission_agent" >/dev/null 2>&1; then
    echo "Commission agent already running"
    return
  fi
  if [[ ! -f workspace/bacnet/commissioning/commission.env ]]; then
    cat >workspace/bacnet/commissioning/commission.env <<EOF
SITE_ID=demo
BUILDING_ID=local
BACNET_BIND=127.0.0.1/24:47808
BACNET_NAME=OpenFddLocal
BACNET_INSTANCE=599999
DISCOVER_LOW=1
DISCOVER_HIGH=4194303
EOF
  fi
  nohup "${VENV}/bin/python" -m bacnet_toolshed.commission_agent \
    >>"${PID_DIR}/commission.log" 2>&1 &
  echo "Commission agent started (discover/write on 127.0.0.1:8767)"
}

start_ui_dev() {
  mkdir -p "$PID_DIR"
  if [[ -f "$UI_PID" ]] && kill -0 "$(cat "$UI_PID")" 2>/dev/null; then
    echo "Vite dev already running"
    return
  fi
  (cd workspace/dashboard && npm ci >/dev/null 2>&1 && npm run dev -- --host 0.0.0.0 --port 5173) \
    >"$UI_LOG" 2>&1 &
  echo $! >"$UI_PID"
  echo "Vite dev pid=$(cat "$UI_PID") → http://0.0.0.0:5173"
}

stop_one() {
  local pidfile="$1" name="$2"
  if [[ -f "$pidfile" ]]; then
    local pid
    pid="$(cat "$pidfile")"
    kill "$pid" 2>/dev/null || true
    sleep 1
    kill -9 "$pid" 2>/dev/null || true
    rm -f "$pidfile"
    echo "Stopped $name"
  fi
}

wait_health() {
  local url="http://127.0.0.1:${OFDD_BRIDGE_PORT}/health"
  for _ in $(seq 1 40); do
    if curl -sf "$url" >/dev/null 2>&1; then
      echo "Bridge health OK"
      return 0
    fi
    sleep 0.5
  done
  echo "Bridge health failed — see ${BRIDGE_LOG}" >&2
  return 1
}

case "$CMD" in
  start)
    start_bridge
    start_commission_agent
    [[ "$DEV_UI" == true ]] && start_ui_dev
    wait_health
    echo ""
    LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
    echo "Dashboard (compiled): http://${LAN_IP}:${OFDD_BRIDGE_PORT}/"
    echo "                     http://127.0.0.1:${OFDD_BRIDGE_PORT}/"
    if systemctl is-active --quiet ufw 2>/dev/null; then
      echo ""
      echo "⚠ UFW is active — remote LAN may TIME OUT until you run:"
      echo "    sudo ${ROOT}/scripts/open_lan_port.sh ${OFDD_BRIDGE_PORT}"
    fi
    [[ "$DEV_UI" == true ]] && echo "Vite dev UI:         http://127.0.0.1:5173/"
    ;;
  stop)
    stop_one "$UI_PID" "vite"
    stop_one "$BRIDGE_PID" "bridge"
    pkill -f "bacnet_toolshed.commission_agent" 2>/dev/null || true
    ;;
  status)
    [[ -f "$BRIDGE_PID" ]] && kill -0 "$(cat "$BRIDGE_PID")" 2>/dev/null && echo "bridge: running" || echo "bridge: stopped"
    pgrep -af commission_agent || echo "commission: stopped"
    curl -sf "http://127.0.0.1:${OFDD_BRIDGE_PORT}/health" && echo || echo "health: down"
    ;;
  build-test)
    ./scripts/build_and_test.sh
    ;;
  *)
    echo "Usage: $0 [start|stop|status|build-test] [--dev]" >&2
    exit 1
    ;;
esac
