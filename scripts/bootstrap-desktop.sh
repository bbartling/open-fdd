#!/usr/bin/env bash
set -euo pipefail

INSTALL_DEPS=0
NO_BRIDGE=0
NO_MCP=0
NO_UI=0
NO_LAUNCH=0
UI_MODE="static" # static|dev
UI_PORT=8080
BRIDGE_URL="${OFDD_BRIDGE_URL:-http://127.0.0.1:8765}"
UI_HOST="${OFDD_UI_HOST:-0.0.0.0}"

step() {
  echo "[open-fdd] $*"
}

die() {
  echo "[open-fdd] $*" >&2
  exit 1
}

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    die "Missing required command: $1"
  fi
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --install-deps) INSTALL_DEPS=1 ;;
      --no-bridge) NO_BRIDGE=1 ;;
      --no-mcp) NO_MCP=1 ;;
      --no-ui) NO_UI=1 ;;
      --no-launch) NO_LAUNCH=1 ;;
      --ui-mode)
        shift
        UI_MODE="${1:-}"
        [[ "${UI_MODE}" == "dev" || "${UI_MODE}" == "static" ]] || die "--ui-mode must be 'dev' or 'static'"
        ;;
      --ui-port)
        shift
        UI_PORT="${1:-}"
        [[ "${UI_PORT}" =~ ^[0-9]+$ ]] || die "--ui-port must be an integer"
        ;;
      --bridge-url)
        shift
        BRIDGE_URL="${1:-}"
        [[ -n "${BRIDGE_URL}" ]] || die "--bridge-url cannot be empty"
        ;;
      -h|--help)
        cat <<'EOF'
Usage: scripts/bootstrap-desktop.sh [options]

Container-first launcher for Open-FDD:
  - FastAPI bridge
  - MCP RAG service
  - Web UI (static server or Vite dev server)

Options:
  --install-deps         Create venv if needed, pip install, and npm install
  --no-bridge            Do not start open-fdd-desktop-bridge
  --no-mcp               Do not start open-fdd-mcp-rag
  --no-ui                Do not start web UI
  --ui-mode <static|dev> UI mode (default: static)
  --ui-port <port>       UI listen port (default: 8080)
  --bridge-url <url>     UI bridge base URL (default: http://127.0.0.1:8765)
  --no-launch            Setup only; do not start processes
  -h, --help             Show this help

Environment:
  OFDD_BRIDGE_URL        Same as --bridge-url (also used by the bridge process bind when set)
  OFDD_BRIDGE_HOST       Optional host override for bridge (if not using OFDD_BRIDGE_URL)
  OFDD_BRIDGE_PORT       Optional port override for bridge (if not using OFDD_BRIDGE_URL)
  OFDD_UI_HOST           Bind host for UI server (default: 0.0.0.0)

Logs:
  .openfdd-bridge.log
  .openfdd-mcp.log
  .openfdd-ui.log
EOF
        exit 0
        ;;
      *)
        die "Unknown argument: $1"
        ;;
    esac
    shift
  done
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WEB_UI_DIR="${REPO_ROOT}/apps/desktop-ui"
VENV_DIR="${REPO_ROOT}/.venv"
VENV_PYTHON="${VENV_DIR}/bin/python"
VENV_ACTIVATE="${VENV_DIR}/bin/activate"

parse_args "$@"

step "Repo root: ${REPO_ROOT}"
[[ -d "${WEB_UI_DIR}" ]] || die "Web UI directory not found: ${WEB_UI_DIR}"

need_cmd python3
need_cmd npm

if [[ ! -x "${VENV_PYTHON}" ]]; then
  step "Creating Python virtualenv..."
  (cd "${REPO_ROOT}" && python3 -m venv .venv)
fi

if [[ "${INSTALL_DEPS}" -eq 1 ]]; then
  step "Installing Python deps..."
  (
    cd "${REPO_ROOT}"
    # shellcheck disable=SC1091
    source "${VENV_ACTIVATE}"
    pip install -U pip
    pip install -e ".[dev,desktop]"
  )

  step "Installing web UI npm deps..."
  (
    cd "${WEB_UI_DIR}"
    if [[ -f package-lock.json ]]; then
      npm ci
    else
      npm install
    fi
  )
fi

if [[ "${NO_LAUNCH}" -eq 1 ]]; then
  step "Setup complete (--no-launch)."
  exit 0
fi

if [[ "${NO_BRIDGE}" -eq 0 ]]; then
  step "Starting FastAPI bridge (${BRIDGE_URL})..."
  (
    cd "${REPO_ROOT}"
    # shellcheck disable=SC1091
    source "${VENV_ACTIVATE}"
    export OFDD_BRIDGE_URL="${BRIDGE_URL}"
    nohup open-fdd-desktop-bridge > "${REPO_ROOT}/.openfdd-bridge.log" 2>&1 &
    echo "[open-fdd] bridge pid=$! log=.openfdd-bridge.log"
  )
fi

if [[ "${NO_MCP}" -eq 0 ]]; then
  step "Starting MCP RAG on 127.0.0.1:8090..."
  (
    cd "${REPO_ROOT}"
    # shellcheck disable=SC1091
    source "${VENV_ACTIVATE}"
    nohup open-fdd-mcp-rag > "${REPO_ROOT}/.openfdd-mcp.log" 2>&1 &
    echo "[open-fdd] mcp pid=$! log=.openfdd-mcp.log"
  )
fi

if [[ "${NO_UI}" -eq 0 ]]; then
  if [[ "${UI_MODE}" == "dev" ]]; then
    step "Starting web UI (Vite dev server) on ${UI_HOST}:${UI_PORT}..."
    (
      cd "${WEB_UI_DIR}"
      export VITE_DESKTOP_BRIDGE_BASE="${BRIDGE_URL}"
      nohup npm run dev -- --host "${UI_HOST}" --port "${UI_PORT}" > "${REPO_ROOT}/.openfdd-ui.log" 2>&1 &
      echo "[open-fdd] ui pid=$! log=.openfdd-ui.log mode=dev"
    )
  else
    step "Building web UI (static) with bridge base ${BRIDGE_URL}..."
    (
      cd "${WEB_UI_DIR}"
      export VITE_DESKTOP_BRIDGE_BASE="${BRIDGE_URL}"
      npm run build
      nohup "${VENV_PYTHON}" -m http.server "${UI_PORT}" --directory dist --bind "${UI_HOST}" > "${REPO_ROOT}/.openfdd-ui.log" 2>&1 &
      echo "[open-fdd] ui pid=$! log=.openfdd-ui.log mode=static"
    )
  fi
fi

step "Ready."
step "Bridge API: ${BRIDGE_URL}"
step "MCP URL:    http://127.0.0.1:8090"
if [[ "${NO_UI}" -eq 0 ]]; then
  step "Web UI:     http://127.0.0.1:${UI_PORT}"
fi
