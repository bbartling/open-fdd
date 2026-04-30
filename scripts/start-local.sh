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

if [[ -f "${REPO_ROOT}/.venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "${REPO_ROOT}/.venv/bin/activate"
fi

export OFDD_DESKTOP_DATA_DIR="${LOCAL_DATA_DIR}"
export OFDD_MODEL_TTL_PATH="${TTL_PATH}"
export OFDD_MODEL_TTL_MIRROR_PATH="${TTL_MIRROR_PATH}"
export OFDD_TTL_SYNC_INTERVAL_SECONDS="${SYNC_INTERVAL}"
export OFDD_BRIDGE_URL="${BRIDGE_URL}"

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
