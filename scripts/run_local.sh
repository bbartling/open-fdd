#!/usr/bin/env bash
# Local edge-like stack: compiled React + bridge on 0.0.0.0:8765 (default).
#
#   ./scripts/run_local.sh start          # build if needed, serve SPA+API
#   ./scripts/run_local.sh start --dev    # also run Vite dev on :5173
#   ./scripts/run_local.sh stop
#   ./scripts/run_local.sh status
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PID_DIR="${ROOT}/workspace/.local-run"
BRIDGE_PID="${PID_DIR}/bridge.pid"
COMMISSION_PID="${PID_DIR}/commission.pid"
OLLAMA_PID="${PID_DIR}/ollama.pid"
UI_PID="${PID_DIR}/ui.pid"
BRIDGE_LOG="${PID_DIR}/bridge.log"
COMMISSION_LOG="${PID_DIR}/commission.log"
OLLAMA_LOG="${PID_DIR}/ollama.log"
UI_LOG="${PID_DIR}/ui.log"

export OPENFDD_REPO_ROOT="$ROOT"
export OPENFDD_WORKSPACE_DIR="${ROOT}/workspace"
export OFDD_DESKTOP_DATA_DIR="${ROOT}/workspace/data"
export PYTHONPATH="$ROOT"
export OFDD_BRIDGE_HOST="${OFDD_BRIDGE_HOST:-0.0.0.0}"
export OFDD_BRIDGE_PORT="${OFDD_BRIDGE_PORT:-8765}"
export OFDD_CORS_ALLOW_PRIVATE_LAN="${OFDD_CORS_ALLOW_PRIVATE_LAN:-1}"

load_env_files() {
  local quiet="${1:-false}"
  if [[ -f "${ROOT}/workspace/auth.env.local" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "${ROOT}/workspace/auth.env.local"
    set +a
    [[ "$quiet" == false ]] && echo "Loaded workspace/auth.env.local (auth enabled if OFDD_AUTH_SECRET set)"
  fi
  if [[ -f "${ROOT}/workspace/ollama.env.local" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "${ROOT}/workspace/ollama.env.local"
    set +a
    [[ "$quiet" == false ]] && echo "Loaded workspace/ollama.env.local (Ollama tier ${OFDD_OLLAMA_RAM_TIER:-unset})"
  fi
}

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

load_env_files "$([[ "$CMD" == "status" ]] && echo true || echo false)"

ensure_build() {
  if [[ ! -f workspace/api/static/app/index.html ]]; then
    ./scripts/build_and_test.sh
  fi
}

pid_running() {
  local pidfile="$1"
  [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null
}

stop_one() {
  local pidfile="$1" name="$2"
  if [[ -f "$pidfile" ]]; then
    local pid
    pid="$(cat "$pidfile")"
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      sleep 1
      kill -9 "$pid" 2>/dev/null || true
    fi
    rm -f "$pidfile"
    echo "Stopped $name (pid $pid)"
  fi
}

stop_by_pattern() {
  local pattern="$1" name="$2"
  if pgrep -f "$pattern" >/dev/null 2>&1; then
    pkill -f "$pattern" 2>/dev/null || true
    sleep 1
    pkill -9 -f "$pattern" 2>/dev/null || true
    echo "Stopped stale $name"
  fi
}

restart_if_running() {
  local pidfile="$1" pattern="$2" name="$3"
  if pid_running "$pidfile"; then
    echo "Restarting $name (pick up code/env changes)…"
    stop_one "$pidfile" "$name"
    return 0
  fi
  if [[ -n "$pattern" ]] && pgrep -f "$pattern" >/dev/null 2>&1; then
    echo "Restarting $name (orphan process, no pid file)…"
    stop_by_pattern "$pattern" "$name"
  fi
}

resolve_ollama_bin() {
  if [[ -x "${ROOT}/workspace/.local-run/ollama/bin/ollama" ]]; then
    echo "${ROOT}/workspace/.local-run/ollama/bin/ollama"
  elif command -v ollama >/dev/null 2>&1; then
    command -v ollama
  fi
}

ollama_base_url() {
  echo "${OFDD_OLLAMA_BASE_URL:-http://127.0.0.1:11434}"
}

ollama_responding() {
  curl -sf "$(ollama_base_url)/api/tags" >/dev/null 2>&1
}

start_bridge() {
  mkdir -p "$PID_DIR" workspace/data workspace/bacnet/commissioning workspace/bacnet/polls
  restart_if_running "$BRIDGE_PID" "uvicorn openfdd_bridge.main:app" "bridge"
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
  restart_if_running "$COMMISSION_PID" "bacnet_toolshed.commission_agent" "commission agent"
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
    >>"$COMMISSION_LOG" 2>&1 &
  echo $! >"$COMMISSION_PID"
  echo "Commission agent pid=$(cat "$COMMISSION_PID") (discover/write on 127.0.0.1:8767)"
}

start_ollama() {
  [[ -f "${ROOT}/workspace/ollama.env.local" ]] || return 0
  local bin
  bin="$(resolve_ollama_bin || true)"
  if [[ -z "$bin" ]]; then
    echo "Ollama env loaded but binary missing — run: ./scripts/bootstrap_ollama.sh --user-local --ram-tier 8gb"
    return 0
  fi

  if pid_running "$OLLAMA_PID"; then
    echo "Restarting Ollama (pick up env changes)…"
    stop_one "$OLLAMA_PID" "ollama"
  elif ollama_responding; then
    echo "Restarting Ollama (already listening on $(ollama_base_url))…"
    stop_by_pattern "${ROOT}/workspace/.local-run/ollama/bin/ollama serve" "ollama"
    if ollama_responding && pgrep -x ollama >/dev/null 2>&1; then
      pkill -x ollama 2>/dev/null || true
      sleep 2
    fi
  fi

  mkdir -p "$PID_DIR"
  nohup "$bin" serve >>"$OLLAMA_LOG" 2>&1 &
  echo $! >"$OLLAMA_PID"
  for _ in $(seq 1 20); do
    if ollama_responding; then
      echo "Ollama pid=$(cat "$OLLAMA_PID") → $(ollama_base_url)"
      return 0
    fi
    sleep 0.5
  done
  echo "Ollama started pid=$(cat "$OLLAMA_PID") but API not ready yet — see ${OLLAMA_LOG}" >&2
}

start_ui_dev() {
  mkdir -p "$PID_DIR"
  restart_if_running "$UI_PID" "vite.*5173" "vite dev"
  (cd workspace/dashboard && npm ci >/dev/null 2>&1 && npm run dev -- --host 0.0.0.0 --port 5173) \
    >"$UI_LOG" 2>&1 &
  echo $! >"$UI_PID"
  echo "Vite dev pid=$(cat "$UI_PID") → http://0.0.0.0:5173"
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

print_lan_note() {
  if systemctl is-active --quiet ufw 2>/dev/null; then
    echo ""
    echo "Note: UFW firewall is active. Localhost works; other LAN clients may need:"
    echo "  sudo ${ROOT}/scripts/open_lan_port.sh ${OFDD_BRIDGE_PORT}"
    echo "(This is informational — start succeeded.)"
  fi
}

case "$CMD" in
  start)
    start_bridge
    start_commission_agent
    start_ollama
    if [[ "$DEV_UI" == true ]]; then
      start_ui_dev
    fi
    wait_health
    echo ""
    LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
    echo "Dashboard (compiled): http://${LAN_IP}:${OFDD_BRIDGE_PORT}/"
    echo "                     http://127.0.0.1:${OFDD_BRIDGE_PORT}/"
    print_lan_note
    if [[ "$DEV_UI" == true ]]; then
      echo "Vite dev UI:         http://127.0.0.1:5173/"
    fi
    ;;
  stop)
    stop_one "$UI_PID" "vite dev"
    stop_one "$OLLAMA_PID" "ollama"
    stop_one "$COMMISSION_PID" "commission agent"
    stop_one "$BRIDGE_PID" "bridge"
    stop_by_pattern "bacnet_toolshed.commission_agent" "commission agent"
    ;;
  restart)
    "$0" stop
    sleep 1
    exec "$0" start "$([[ "$DEV_UI" == true ]] && echo --dev)"
    ;;
  status)
    if pid_running "$BRIDGE_PID"; then
      echo "bridge: running pid=$(cat "$BRIDGE_PID")"
    else
      echo "bridge: stopped"
    fi
    if pid_running "$COMMISSION_PID"; then
      echo "commission: running pid=$(cat "$COMMISSION_PID")"
    elif pgrep -af "bacnet_toolshed.commission_agent" >/dev/null 2>&1; then
      echo "commission: running (orphan, no pid file)"
      pgrep -af "bacnet_toolshed.commission_agent" || true
    else
      echo "commission: stopped"
    fi
    if [[ -f "${ROOT}/workspace/ollama.env.local" ]]; then
      if pid_running "$OLLAMA_PID"; then
        echo "ollama: running pid=$(cat "$OLLAMA_PID")"
      elif ollama_responding; then
        echo "ollama: responding at $(ollama_base_url) (pid file missing)"
      else
        echo "ollama: stopped"
      fi
    fi
    if pid_running "$UI_PID"; then
      echo "vite dev: running pid=$(cat "$UI_PID")"
    fi
    if curl -sf "http://127.0.0.1:${OFDD_BRIDGE_PORT}/health" >/dev/null 2>&1; then
      echo "health: ok"
    else
      echo "health: down"
    fi
    ;;
  build-test)
    ./scripts/build_and_test.sh
    ;;
  *)
    echo "Usage: $0 [start|stop|restart|status|build-test] [--dev]" >&2
    exit 1
    ;;
esac
