#!/usr/bin/env bash
# Local edge-like stack: Caddy :80 (or :443 TLS) → bridge 127.0.0.1:8765 → compiled React in static/app.
# Same UI delivery as Ansible deploy (rsync workspace/api/static/app — no npm on the remote host).
#
#   ./scripts/run_local.sh              # build production UI + start stack
#   ./scripts/run_local.sh start        # Caddy + bridge + commission + ollama + MCP RAG
#   ./scripts/run_local.sh restart      # stop, rebuild production UI, start
#   ./scripts/run_local.sh stop
#   ./scripts/run_local.sh status
#   OFDD_SKIP_UI_BUILD=1 ./scripts/run_local.sh restart   # skip npm (UI unchanged)
#
# UI build modes (before start/restart):
#   --ui-prod     production vite build (default)
#   --ui-test     vitest + production build (CI-style gate)
#   --ui-skip     skip UI build (same as OFDD_SKIP_UI_BUILD=1)
#
# Optional (NOT production parity — Vite HMR on :5173):
#   ./scripts/run_local.sh start --dev
#
# Caddy config: workspace/caddy.env.local (copy from caddy.env.example)
# Feather / data cap: workspace/data.env.local overrides defaults (see load_data_env in run_local.sh)
#   OFDD_CADDY_MODE=http | tls | off
# Self-signed TLS: ./scripts/setup_caddy_certs.sh then OFDD_CADDY_MODE=tls
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PID_DIR="${ROOT}/workspace/.local-run"
BRIDGE_PID="${PID_DIR}/bridge.pid"
COMMISSION_PID="${PID_DIR}/commission.pid"
OLLAMA_PID="${PID_DIR}/ollama.pid"
CADDY_PID="${PID_DIR}/caddy.pid"
MCP_PID="${PID_DIR}/mcp_rag.pid"
FDD_PID="${PID_DIR}/fdd_loop.pid"
FDD_LOG="${PID_DIR}/fdd_loop.log"
BRIDGE_LOG="${PID_DIR}/bridge.log"
COMMISSION_LOG="${PID_DIR}/commission.log"
OLLAMA_LOG="${PID_DIR}/ollama.log"
CADDY_LOG="${PID_DIR}/caddy.log"
MCP_LOG="${PID_DIR}/mcp_rag.log"
UI_PID="${PID_DIR}/ui.pid"
UI_LOG="${PID_DIR}/ui.log"

export OPENFDD_REPO_ROOT="$ROOT"
export OPENFDD_WORKSPACE_DIR="${ROOT}/workspace"
export OFDD_DESKTOP_DATA_DIR="${ROOT}/workspace/data"
export PYTHONPATH="${ROOT}/workspace/api:${ROOT}"
export OFDD_BRIDGE_HOST="${OFDD_BRIDGE_HOST:-0.0.0.0}"
export OFDD_BRIDGE_PORT="${OFDD_BRIDGE_PORT:-8765}"
export OFDD_FDD_LOOKBACK_HOURS="${OFDD_FDD_LOOKBACK_HOURS:-1}"
export OFDD_FDD_INTERVAL_MINUTES="${OFDD_FDD_INTERVAL_MINUTES:-60}"

load_data_env() {
  local quiet="${1:-false}"
  if [[ -f "${ROOT}/workspace/data.env.local" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "${ROOT}/workspace/data.env.local"
    set +a
    if [[ "$quiet" == false ]]; then
      echo "Loaded workspace/data.env.local (feather max ${OFDD_FEATHER_MAX_GIB:-0} GiB, retention ${OFDD_FEATHER_RETENTION_DAYS:-?}d)"
    fi
  else
    # Match workspace/data.env.example — used when no .local override exists.
    export OFDD_FEATHER_MAX_GIB="${OFDD_FEATHER_MAX_GIB:-5}"
    export OFDD_FEATHER_RETENTION_DAYS="${OFDD_FEATHER_RETENTION_DAYS:-90}"
    export OFDD_FEATHER_TRIM_CHUNK_HOURS="${OFDD_FEATHER_TRIM_CHUNK_HOURS:-24}"
    if [[ "$quiet" == false ]]; then
      echo "Feather storage defaults (no data.env.local): max ${OFDD_FEATHER_MAX_GIB} GiB, retention ${OFDD_FEATHER_RETENTION_DAYS}d, trim ${OFDD_FEATHER_TRIM_CHUNK_HOURS}h"
    fi
  fi
}

load_env_files() {
  local quiet="${1:-false}"
  if [[ -f "${ROOT}/workspace/pentest.env.local" ]] && [[ "${OFDD_PENTEST_MODE:-0}" == "1" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "${ROOT}/workspace/pentest.env.local"
    set +a
    [[ "$quiet" == false ]] && echo "Loaded workspace/pentest.env.local (pentest / production-like mode)" || true
  fi
  if [[ "${OFDD_PENTEST_MODE:-0}" == "1" && -f "${ROOT}/workspace/auth.pentest.local" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "${ROOT}/workspace/auth.pentest.local"
    set +a
    [[ "$quiet" == false ]] && echo "Loaded workspace/auth.pentest.local (pentest credentials — not auth.env.example)" || true
  elif [[ -f "${ROOT}/workspace/auth.env.local" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "${ROOT}/workspace/auth.env.local"
    set +a
    [[ "$quiet" == false ]] && echo "Loaded workspace/auth.env.local (auth enabled if OFDD_AUTH_SECRET set)" || true
  fi
  if [[ -f "${ROOT}/workspace/ollama.env.local" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "${ROOT}/workspace/ollama.env.local"
    set +a
    [[ "$quiet" == false ]] && echo "Loaded workspace/ollama.env.local (Ollama tier ${OFDD_OLLAMA_RAM_TIER:-unset})" || true
  fi
  if [[ -f "${ROOT}/workspace/caddy.env.local" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "${ROOT}/workspace/caddy.env.local"
    set +a
    [[ "$quiet" == false ]] && echo "Loaded workspace/caddy.env.local (Caddy mode ${OFDD_CADDY_MODE:-http})" || true
  elif [[ -f "${ROOT}/workspace/caddy.env.example" ]] && [[ "$CMD" == "start" || "$CMD" == "up" || "$CMD" == "restart" ]]; then
    cp "${ROOT}/workspace/caddy.env.example" "${ROOT}/workspace/caddy.env.local"
    set -a
    # shellcheck disable=SC1091
    source "${ROOT}/workspace/caddy.env.local"
    set +a
    echo "Created workspace/caddy.env.local from example (Caddy on :80 by default)"
  fi
  if [[ -f "${ROOT}/workspace/mcp.env.local" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "${ROOT}/workspace/mcp.env.local"
    set +a
    [[ "$quiet" == false ]] && echo "Loaded workspace/mcp.env.local (MCP RAG ${OFDD_MCP_ENABLED:-off})" || true
  elif [[ -f "${ROOT}/workspace/mcp.env.example" ]] && [[ "$CMD" == "start" || "$CMD" == "up" || "$CMD" == "restart" ]]; then
    cp "${ROOT}/workspace/mcp.env.example" "${ROOT}/workspace/mcp.env.local"
    set -a
    # shellcheck disable=SC1091
    source "${ROOT}/workspace/mcp.env.local"
    set +a
    echo "Created workspace/mcp.env.local from example (MCP RAG on :8090)"
  fi
  load_data_env "$quiet"
}

VENV="${ROOT}/.venv"
DEV_UI=false
UI_BUILD_MODE="prod"
CMD="${1:-start}"
shift || true
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dev) DEV_UI=true; shift ;;
    --ui-prod) UI_BUILD_MODE=prod; shift ;;
    --ui-test) UI_BUILD_MODE=test; shift ;;
    --ui-skip) UI_BUILD_MODE=skip; shift ;;
    *) shift ;;
  esac
done

if [[ "${OFDD_SKIP_UI_BUILD:-0}" == "1" ]]; then
  UI_BUILD_MODE=skip
fi

ui_build_restart_args() {
  local args=()
  [[ "$DEV_UI" == true ]] && args+=(--dev)
  case "$UI_BUILD_MODE" in
    test) args+=(--ui-test) ;;
    skip) args+=(--ui-skip) ;;
    prod) args+=(--ui-prod) ;;
  esac
  # Single line for safe use in: exec "$0" start $(ui_build_restart_args)
  echo "${args[*]}"
}

load_env_files "$([[ "$CMD" == "status" ]] && echo true || echo false)"

caddy_enabled() {
  [[ "${OFDD_CADDY_ENABLED:-0}" == "1" ]] && [[ "${OFDD_CADDY_MODE:-http}" != "off" ]]
}

apply_caddy_bridge_bind() {
  if caddy_enabled; then
    export OFDD_BRIDGE_HOST=127.0.0.1
    export OFDD_CORS_ALLOW_PRIVATE_LAN=1
  fi
}

apply_caddy_bridge_bind

ensure_build() {
  case "$UI_BUILD_MODE" in
    skip)
      if [[ ! -f workspace/api/static/app/index.html ]]; then
        echo "UI build skipped but workspace/api/static/app/index.html is missing — run with --ui-prod or --ui-test" >&2
        exit 1
      fi
      echo "Skipping UI build (--ui-skip / OFDD_SKIP_UI_BUILD=1) — serving existing production bundle"
      ;;
    test)
      echo "==> Dashboard test + production build (vitest, then vite build)"
      ./scripts/build_operator_dashboard.sh test
      test -f workspace/api/static/app/index.html
      ;;
    prod|*)
      echo "==> Production React dashboard (same artifact Ansible rsyncs to edge hosts)"
      ./scripts/build_operator_dashboard.sh prod
      test -f workspace/api/static/app/index.html
      ;;
  esac
}

pid_running() {
  local pidfile="$1"
  [[ -f "$pidfile" ]] || return 1
  kill -0 "$(cat "$pidfile")" 2>/dev/null
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

write_caddyfile() {
  local mode="${OFDD_CADDY_MODE:-http}"
  local cfg="${PID_DIR}/Caddyfile"
  local cert_dir="${ROOT}/workspace/deploy/caddy/certs"
  local http_port="${OFDD_CADDY_HTTP_PORT:-80}"
  mkdir -p "$PID_DIR"
  if [[ "$mode" == "tls" ]]; then
    if [[ ! -f "${cert_dir}/cert.pem" ]]; then
      OFDD_CADDY_TLS_CN="${OFDD_CADDY_TLS_CN:-openfdd.local}" "${ROOT}/scripts/setup_caddy_certs.sh"
    fi
    cat >"$cfg" <<EOF
:80 {
	redir https://{host}{uri} permanent
}
:443 {
	tls ${cert_dir}/cert.pem ${cert_dir}/key.pem
	header {
		Strict-Transport-Security "max-age=31536000; includeSubDomains"
		X-Content-Type-Options nosniff
		X-Frame-Options SAMEORIGIN
		Referrer-Policy strict-origin-when-cross-origin
	}
	reverse_proxy 127.0.0.1:${OFDD_BRIDGE_PORT}
}
EOF
  else
    cat >"$cfg" <<EOF
:${http_port} {
	header {
		X-Content-Type-Options nosniff
		X-Frame-Options SAMEORIGIN
		Referrer-Policy strict-origin-when-cross-origin
	}
	reverse_proxy 127.0.0.1:${OFDD_BRIDGE_PORT}
}
EOF
  fi
  echo "$cfg"
}

caddy_entry_url() {
  if [[ "${OFDD_CADDY_MODE:-http}" == "tls" ]]; then
    echo "https://127.0.0.1/"
  elif [[ "${OFDD_CADDY_HTTP_PORT:-80}" != "80" ]]; then
    echo "http://127.0.0.1:${OFDD_CADDY_HTTP_PORT}/"
  else
    echo "http://127.0.0.1/"
  fi
}

_caddy_wait_ready() {
  local entry="$1"
  curl -sfk "${entry%/}/health" >/dev/null 2>&1
}

start_caddy() {
  caddy_enabled || return 0
  if ! command -v caddy >/dev/null 2>&1; then
    echo "Caddy enabled but 'caddy' not in PATH — install: sudo apt install caddy" >&2
    return 0
  fi
  local bin
  bin="$(command -v caddy)"
  if ! getcap "$bin" 2>/dev/null | grep -q cap_net_bind_service; then
    if sudo -n setcap 'cap_net_bind_service=+ep' "$bin" 2>/dev/null; then
      echo "Granted Caddy CAP_NET_BIND_SERVICE for :80"
    elif [[ "${OFDD_CADDY_HTTP_PORT:-80}" == "80" ]]; then
      echo "Tip: for :80 without sudo — sudo setcap 'cap_net_bind_service=+ep' $bin" >&2
    fi
  fi
  restart_if_running "$CADDY_PID" "caddy run --config ${PID_DIR}/Caddyfile" "caddy"
  : >"$CADDY_LOG"
  local cfg entry
  cfg="$(write_caddyfile)"
  nohup caddy run --config "$cfg" --adapter caddyfile >>"$CADDY_LOG" 2>&1 &
  echo $! >"$CADDY_PID"
  entry="$(caddy_entry_url)"
  for _ in $(seq 1 30); do
    if _caddy_wait_ready "$entry"; then
      echo "Caddy pid=$(cat "$CADDY_PID") → ${entry} (check-engine dashboard)"
      return 0
    fi
    sleep 0.5
  done
  if [[ "${OFDD_CADDY_MODE:-http}" == "http" ]] && [[ "${OFDD_CADDY_HTTP_PORT:-80}" == "80" ]] \
      && grep -q "permission denied" "$CADDY_LOG" 2>/dev/null; then
    echo "Caddy :80 permission denied — retrying on :8080 for local dev (Ansible edge uses :80 with setcap)" >&2
    stop_one "$CADDY_PID" "caddy"
    export OFDD_CADDY_HTTP_PORT=8080
    cfg="$(write_caddyfile)"
    nohup caddy run --config "$cfg" --adapter caddyfile >>"$CADDY_LOG" 2>&1 &
    echo $! >"$CADDY_PID"
    entry="$(caddy_entry_url)"
    for _ in $(seq 1 20); do
      if _caddy_wait_ready "$entry"; then
        echo "Caddy pid=$(cat "$CADDY_PID") → ${entry} (local dev fallback; edge deploy uses :80)"
        return 0
      fi
      sleep 0.5
    done
  fi
  echo "Caddy started pid=$(cat "$CADDY_PID") but entry URL not ready — see ${CADDY_LOG}" >&2
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
    local bacnet_bind
    bacnet_bind="$("${VENV}/bin/python" -c "from bacnet_toolshed.nic_bind import resolve_bacnet_bind; print(resolve_bacnet_bind(''))")"
    cat >workspace/bacnet/commissioning/commission.env <<EOF
SITE_ID=demo
BUILDING_ID=local
BACNET_BIND=${bacnet_bind}
BACNET_NAME=OpenFDD
BACNET_INSTANCE=599999
DISCOVER_LOW=1
DISCOVER_HIGH=4194303
EOF
    echo "Created commission.env with BACnet bind ${bacnet_bind} (NIC IP — not 127.0.0.1)"
  fi
  nohup "${VENV}/bin/python" -m bacnet_toolshed.commission_agent \
    >>"$COMMISSION_LOG" 2>&1 &
  echo $! >"$COMMISSION_PID"
  echo "Commission agent pid=$(cat "$COMMISSION_PID") (discover/write on 127.0.0.1:8767)"
}

mcp_enabled() {
  case "${OFDD_MCP_ENABLED:-0}" in 1|true|yes|TRUE|YES) return 0 ;; *) return 1 ;; esac
}

ensure_mcp_index() {
  local idx="${OFDD_MCP_RAG_INDEX_PATH:-${ROOT}/workspace/data/mcp/rag_index.json}"
  if [[ ! -f "$idx" ]]; then
    echo "Building MCP RAG index (first run)…"
    "${ROOT}/scripts/build_mcp_rag_index.sh"
  fi
}

mcp_base_url() {
  echo "${OFDD_MCP_REST_BASE:-http://127.0.0.1:${OFDD_MCP_LISTEN_PORT:-8090}}"
}

start_mcp_rag() {
  mcp_enabled || return 0
  export OFDD_MCP_RAG_INDEX_PATH="${OFDD_MCP_RAG_INDEX_PATH:-${ROOT}/workspace/data/mcp/rag_index.json}"
  ensure_mcp_index
  local host="${OFDD_MCP_LISTEN_HOST:-127.0.0.1}"
  local port="${OFDD_MCP_LISTEN_PORT:-8090}"
  restart_if_running "$MCP_PID" "uvicorn mcp_rag.app:app" "MCP RAG"
  mkdir -p "$PID_DIR"
  "${VENV}/bin/pip" install -q -r workspace/api/requirements.txt
  nohup "${VENV}/bin/uvicorn" mcp_rag.app:app \
    --app-dir workspace \
    --host "$host" --port "$port" \
    >"$MCP_LOG" 2>&1 &
  echo $! >"$MCP_PID"
  local base
  base="$(mcp_base_url)"
  for _ in $(seq 1 20); do
    if curl -sf "${base%/}/health" >/dev/null 2>&1; then
      echo "MCP RAG pid=$(cat "$MCP_PID") → ${base}"
      return 0
    fi
    sleep 0.5
  done
  echo "MCP RAG started pid=$(cat "$MCP_PID") but /health not ready — see ${MCP_LOG}" >&2
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

start_fdd_loop() {
  mkdir -p "$PID_DIR"
  restart_if_running "$FDD_PID" "openfdd_bridge.fdd_runner" "FDD loop"
  "${VENV}/bin/pip" install -q -e ".[dev,engine]" -r workspace/api/requirements.txt
  (
    cd "${ROOT}/workspace/api"
    nohup "${VENV}/bin/python" -m openfdd_bridge.fdd_runner \
      --loop --interval-minutes "${OFDD_FDD_INTERVAL_MINUTES}" \
      --lookback-hours "${OFDD_FDD_LOOKBACK_HOURS}" \
      >>"$FDD_LOG" 2>&1 &
    echo $! >"$FDD_PID"
  )
  echo "FDD loop pid=$(cat "$FDD_PID") every ${OFDD_FDD_INTERVAL_MINUTES}m lookback ${OFDD_FDD_LOOKBACK_HOURS}h → ${FDD_LOG}"
}

start_ui_dev() {
  echo "WARNING: --dev serves Vite on :5173 (HMR). For Ansible/production parity use the default start without --dev." >&2
  mkdir -p "$PID_DIR"
  restart_if_running "$UI_PID" "vite.*5173" "vite dev"
  (cd workspace/dashboard && npm ci >/dev/null 2>&1 && npm run dev -- --host 0.0.0.0 --port 5173) \
    >"$UI_LOG" 2>&1 &
  echo $! >"$UI_PID"
  echo "Vite dev pid=$(cat "$UI_PID") → http://0.0.0.0:5173 (not production — use Caddy/bridge URL for parity)"
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
  start|up)
    start_mcp_rag
    start_bridge
    start_commission_agent
    start_ollama
    if [[ "$DEV_UI" == true ]]; then
      start_ui_dev
    fi
    wait_health
    start_fdd_loop
    start_caddy
    echo ""
    LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
    if caddy_enabled; then
      if [[ "${OFDD_CADDY_MODE:-http}" == "tls" ]]; then
        echo "Check-engine dashboard: https://${LAN_IP}/"
        echo "                     https://127.0.0.1/  (self-signed — browser warning OK on OT LAN)"
      elif [[ "${OFDD_CADDY_HTTP_PORT:-80}" != "80" ]]; then
        echo "Check-engine dashboard: http://${LAN_IP}:${OFDD_CADDY_HTTP_PORT}/"
        echo "                     http://127.0.0.1:${OFDD_CADDY_HTTP_PORT}/  (local dev fallback port)"
      else
        echo "Check-engine dashboard: http://${LAN_IP}/"
        echo "                     http://127.0.0.1/  (no port — public traffic-light view)"
      fi
      echo "Bridge (internal):     http://127.0.0.1:${OFDD_BRIDGE_PORT}/"
    else
      echo "Dashboard (compiled): http://${LAN_IP}:${OFDD_BRIDGE_PORT}/"
      echo "                     http://127.0.0.1:${OFDD_BRIDGE_PORT}/  (production static/app bundle)"
    fi
    print_lan_note
    if [[ "$DEV_UI" == true ]]; then
      echo "Vite dev (optional): http://127.0.0.1:5173/  — not the same as Ansible/production UI"
    fi
    ;;
  stop)
    stop_one "$FDD_PID" "FDD loop"
    stop_by_pattern "openfdd_bridge.fdd_runner" "FDD loop"
    stop_one "$UI_PID" "vite dev"
    stop_one "$CADDY_PID" "caddy"
    stop_by_pattern "caddy run --config ${PID_DIR}/Caddyfile" "caddy"
    stop_one "$MCP_PID" "MCP RAG"
    stop_by_pattern "uvicorn mcp_rag.app:app" "MCP RAG"
    stop_one "$OLLAMA_PID" "ollama"
    stop_one "$COMMISSION_PID" "commission agent"
    stop_one "$BRIDGE_PID" "bridge"
    stop_by_pattern "bacnet_toolshed.commission_agent" "commission agent"
    ;;
  restart)
    "$0" stop
    sleep 1
    # shellcheck disable=SC2046
    exec "$0" start $(ui_build_restart_args)
    ;;
  status)
    if pid_running "$FDD_PID"; then
      echo "fdd_loop: running pid=$(cat "$FDD_PID") (every ${OFDD_FDD_INTERVAL_MINUTES:-60}m, lookback ${OFDD_FDD_LOOKBACK_HOURS:-1}h)"
    elif pgrep -af "openfdd_bridge.fdd_runner" >/dev/null 2>&1; then
      echo "fdd_loop: running (orphan)"
    else
      echo "fdd_loop: stopped"
    fi
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
    if mcp_enabled; then
      if pid_running "$MCP_PID"; then
        echo "mcp_rag: running pid=$(cat "$MCP_PID")"
      elif curl -sf "$(mcp_base_url)/health" >/dev/null 2>&1; then
        echo "mcp_rag: responding at $(mcp_base_url) (pid file missing)"
      else
        echo "mcp_rag: stopped"
      fi
    elif [[ -f "${ROOT}/workspace/mcp.env.local" ]]; then
      echo "mcp_rag: disabled (OFDD_MCP_ENABLED not set)"
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
    if caddy_enabled; then
      if pid_running "$CADDY_PID"; then
        echo "caddy: running pid=$(cat "$CADDY_PID") mode=${OFDD_CADDY_MODE:-http}"
      else
        echo "caddy: stopped (enabled in caddy.env.local)"
      fi
    fi
    if caddy_enabled; then
      if curl -sfk "$(caddy_entry_url)health" >/dev/null 2>&1; then
        echo "health (via Caddy): ok"
      else
        echo "health (via Caddy): down"
      fi
    elif curl -sf "http://127.0.0.1:${OFDD_BRIDGE_PORT}/health" >/dev/null 2>&1; then
      echo "health: ok"
    else
      echo "health: down"
    fi
    ;;
  build-test)
    ./scripts/build_and_test.sh
    ;;
  feather-maintain|feather)
    (cd "${ROOT}/workspace/api" && "${VENV}/bin/python" -m openfdd_bridge.feather_store --maintain)
    ;;
  *)
    echo "Usage: $0 [start|up|stop|restart|status|build-test|feather-maintain] [--dev] [--ui-prod|--ui-test|--ui-skip]" >&2
    exit 1
    ;;
esac
