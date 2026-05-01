#!/usr/bin/env bash
set -euo pipefail

ROLE="${1:-all}"
BRIDGE_URL="${OFDD_BRIDGE_URL:-http://127.0.0.1:8765}"
SYNC_INTERVAL="${OFDD_TTL_SYNC_INTERVAL_SECONDS:-5}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DESKTOP_UI_DIR="${REPO_ROOT}/apps/desktop-ui"
LOCAL_DATA_DIR="${REPO_ROOT}/stack/local-data"
TTL_PATH="${LOCAL_DATA_DIR}/data_model.ttl"
TTL_MIRROR_PATH="${LOCAL_DATA_DIR}/data_model.mirror.ttl"
LOG_DIR="${LOCAL_DATA_DIR}/logs"

mkdir -p "${LOCAL_DATA_DIR}" "${LOG_DIR}"

needs_venv() {
  [[ "${ROLE}" != "ui" ]]
}

if needs_venv && [[ ! -f "${REPO_ROOT}/.venv/bin/activate" ]]; then
  echo "Missing venv: ${REPO_ROOT}/.venv/bin/activate (create .venv and pip install open-fdd[desktop] before gateway/mcp/adapter)." >&2
  exit 1
fi

if [[ -f "${REPO_ROOT}/.venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "${REPO_ROOT}/.venv/bin/activate"
fi

export OFDD_DESKTOP_DATA_DIR="${LOCAL_DATA_DIR}"
export OFDD_MODEL_TTL_PATH="${TTL_PATH}"
export OFDD_MODEL_TTL_MIRROR_PATH="${TTL_MIRROR_PATH}"
export OFDD_TTL_SYNC_INTERVAL_SECONDS="${SYNC_INTERVAL}"
export OFDD_BRIDGE_URL="${BRIDGE_URL}"
export OFDD_MCP_OFDD_API_URL="${BRIDGE_URL}"
export OFDD_UI_PUBLIC_BASE="${OFDD_UI_PUBLIC_BASE:-http://127.0.0.1:5173}"

start_bg() {
  local name="$1"
  shift
  nohup "$@" >"${LOG_DIR}/${name}.log" 2>&1 &
  echo "Started ${name} (pid=$!), log=${LOG_DIR}/${name}.log"
}

case "${ROLE}" in
  all)
    (
      cd "${REPO_ROOT}"
      start_bg "gateway" open-fdd-gateway
      start_bg "mcp-rag" open-fdd-mcp-rag
    )
    (
      cd "${DESKTOP_UI_DIR}"
      start_bg "desktop-ui" npm run dev
    )
    echo "All services launched with repo-local data defaults."
    echo ""
    echo "Open-FDD UI:        ${OFDD_UI_PUBLIC_BASE}"
    echo "Plots (FDD-ready):  ${OFDD_UI_PUBLIC_BASE}/plots?fdd=1&skipMissing=1&runSource=csv"
    echo "  Add site_id=<uuid> after you ingest (see GET ${BRIDGE_URL}/assistant/readiness) for one-click overlay."
    echo "Bridge health:      ${BRIDGE_URL}/health"
    echo "If the browser shows ERR_CONNECTION_REFUSED, the gateway window was closed or failed to bind; re-run this script."
    echo "Background logs:    ${LOG_DIR}/gateway.log  ${LOG_DIR}/mcp-rag.log  ${LOG_DIR}/desktop-ui.log"
    health_ok=0
    for _i in $(seq 1 30); do
      if command -v curl >/dev/null 2>&1; then
        if curl -sf "${BRIDGE_URL}/health" >/dev/null 2>&1; then
          health_ok=1
          break
        fi
      elif command -v wget >/dev/null 2>&1; then
        if wget -qO- "${BRIDGE_URL}/health" >/dev/null 2>&1; then
          health_ok=1
          break
        fi
      else
        echo "WARNING: neither curl nor wget found; skipping bridge health wait. Install curl for smoke checks."
        break
      fi
      sleep 1
    done
    if [[ "${health_ok}" -eq 1 ]]; then
      echo "Bridge responded OK at ${BRIDGE_URL}/health (UI may need a few more seconds for Vite)."
    elif command -v curl >/dev/null 2>&1 || command -v wget >/dev/null 2>&1; then
      echo "WARNING: Bridge did not respond at ${BRIDGE_URL}/health within 30s. Check ${LOG_DIR}/gateway.log"
    fi
    ;;
  gateway)
    cd "${REPO_ROOT}"
    exec open-fdd-gateway
    ;;
  mcp)
    cd "${REPO_ROOT}"
    exec open-fdd-mcp-rag
    ;;
  adapter)
    cd "${REPO_ROOT}"
    exec open-fdd-mcp-adapter
    ;;
  ui)
    cd "${DESKTOP_UI_DIR}"
    exec npm run dev
    ;;
  *)
    echo "Unknown role '${ROLE}'. Use: all|gateway|mcp|adapter|ui" >&2
    exit 1
    ;;
esac
