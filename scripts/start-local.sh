#!/usr/bin/env bash
set -euo pipefail

ROLE="${1:-all}"
BRIDGE_URL="${OFDD_BRIDGE_URL:-http://127.0.0.1:8765}"
# Match start-local.ps1 / gateway: avoid double slashes when joining paths.
BRIDGE_URL="${BRIDGE_URL%/}"
SYNC_INTERVAL="${OFDD_TTL_SYNC_INTERVAL_SECONDS:-5}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DESKTOP_UI_DIR="${REPO_ROOT}/apps/desktop-ui"
LOCAL_DATA_DIR="${REPO_ROOT}/stack/local-data"
TTL_PATH="${LOCAL_DATA_DIR}/data_model.ttl"
TTL_MIRROR_PATH="${LOCAL_DATA_DIR}/data_model.mirror.ttl"
LOG_DIR="${LOCAL_DATA_DIR}/logs"

mkdir -p "${LOCAL_DATA_DIR}" "${LOG_DIR}"

# Match scripts/start-local.ps1: agent + Codex see merged URLs via OFDD_AGENT_BOOTSTRAP_FILE.
write_openfdd_agent_bootstrap() {
  local role_tag="$1"
  local bootstrap_path="${LOCAL_DATA_DIR}/openfdd-agent-bootstrap.json"
  local bridge_trim="${BRIDGE_URL%/}"
  local mcp_rest="${OFDD_MCP_REST_BASE:-http://127.0.0.1:8090}"
  mcp_rest="${mcp_rest%/}"
  local ui_pub="${OFDD_UI_PUBLIC_BASE:-http://127.0.0.1:5173}"
  ui_pub="${ui_pub%/}"
  unset OFDD_AGENT_BOOTSTRAP_FILE 2>/dev/null || true
  if ! command -v python3 >/dev/null 2>&1; then
    echo "WARNING: python3 not found; could not write ${bootstrap_path}. Set OFDD_BRIDGE_URL / OFDD_UI_PUBLIC_BASE manually for Codex." >&2
    return 0
  fi
  python3 - "${bootstrap_path}" "${bridge_trim}" "${mcp_rest}" "${ui_pub}" "${LOCAL_DATA_DIR}" "${role_tag}" <<'PY'
import json, pathlib, sys

path, bridge, mcp, ui, data_dir, role = sys.argv[1:7]
doc = {
    "bridge_base": bridge,
    "mcp_rest_base": mcp,
    "ui_public_base": ui,
    "started_with": "scripts/start-local.sh",
    "role": role,
    "desktop_data_dir": data_dir,
    "notes": [
        "Open-FDD built-in agent reads this file via OFDD_AGENT_BOOTSTRAP_FILE (set on child processes).",
        f"GET {bridge}/openfdd-agent/context for live merged JSON from the bridge.",
        f"MCP: GET {mcp}/manifest - REST tools under POST {mcp}/tools/...",
    ],
}
pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
pathlib.Path(path).write_text(json.dumps(doc, indent=2), encoding="utf-8")
PY
  export OFDD_AGENT_BOOTSTRAP_FILE="${bootstrap_path}"
  echo "Wrote agent bootstrap: ${bootstrap_path}"
}

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
# Trim trailing slashes on exported bases (same behavior as Get-Ofdd* in start-local.ps1).
_ui_pub="${OFDD_UI_PUBLIC_BASE:-http://127.0.0.1:5173}"
export OFDD_UI_PUBLIC_BASE="${_ui_pub%/}"
_mcp_rest="${OFDD_MCP_REST_BASE:-http://127.0.0.1:8090}"
export OFDD_MCP_REST_BASE="${_mcp_rest%/}"
# Global npm install from POST /local-codex/install-cli: opt in with OFDD_ALLOW_LOCAL_CODEX_INSTALL_CLI=1.
export OFDD_ALLOW_LOCAL_CODEX_INSTALL_CLI="${OFDD_ALLOW_LOCAL_CODEX_INSTALL_CLI:-0}"

start_bg() {
  local name="$1"
  shift
  nohup "$@" >"${LOG_DIR}/${name}.log" 2>&1 &
  echo "Started ${name} (pid=$!), log=${LOG_DIR}/${name}.log"
}

case "${ROLE}" in
  all)
    write_openfdd_agent_bootstrap "all"
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
    printf '%s\n' 'Tip: Re-running this script without closing the previous gateway / mcp-rag / desktop-ui windows can leave ports 8765, 8090, or 5173 busy. Close old windows (or stop old PIDs) to refresh MCP and pick up a rebuilt rag_index.json — see docs/howto/desktop_app.md (Restarting start-local and MCP).'
    echo ""
    echo "Open-FDD UI:        ${OFDD_UI_PUBLIC_BASE}"
    echo "Open-FDD agent API: ${BRIDGE_URL}/openfdd-agent/context  (POST .../openfdd-agent/chat)"
    echo "MCP RAG REST:       ${OFDD_MCP_REST_BASE}/manifest"
    printf 'Plots (FDD-ready):  %s/plots?fdd=1&skipMissing=1&runSource=csv\n' "${OFDD_UI_PUBLIC_BASE}"
    printf '  Add site_id=<uuid> after you ingest (see GET %s/assistant/readiness) for one-click overlay.\n' "${BRIDGE_URL}"
    echo "Bridge health:      ${BRIDGE_URL}/health"
    printf '%s\n' 'If the browser shows ERR_CONNECTION_REFUSED, the gateway window was closed or failed to bind; re-run this script.'
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
    write_openfdd_agent_bootstrap "gateway"
    cd "${REPO_ROOT}"
    exec open-fdd-gateway
    ;;
  mcp)
    write_openfdd_agent_bootstrap "mcp"
    cd "${REPO_ROOT}"
    exec open-fdd-mcp-rag
    ;;
  adapter)
    write_openfdd_agent_bootstrap "adapter"
    cd "${REPO_ROOT}"
    exec open-fdd-mcp-adapter
    ;;
  ui)
    write_openfdd_agent_bootstrap "ui"
    cd "${DESKTOP_UI_DIR}"
    exec npm run dev
    ;;
  *)
    echo "Unknown role '${ROLE}'. Use: all|gateway|mcp|adapter|ui" >&2
    exit 1
    ;;
esac
