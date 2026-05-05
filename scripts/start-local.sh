#!/usr/bin/env bash
set -euo pipefail

# Optional: bash scripts/start-local.sh --lan-host 192.168.1.10 all
# Same as PowerShell -LanHost: bind gateway+MCP on 0.0.0.0, Vite --host 0.0.0.0, CORS for private LAN, set public URLs.
ROLE="all"
LAN_HOST=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --lan-host)
      LAN_HOST="${2:-}"
      if [[ -z "${LAN_HOST}" ]]; then
        echo "start-local.sh: --lan-host requires an IPv4 (e.g. 192.168.1.10)" >&2
        exit 1
      fi
      shift 2
      ;;
    all|gateway|mcp|ui|adapter)
      ROLE="$1"
      shift
      ;;
    *)
      echo "start-local.sh: unknown argument '$1' (use [--lan-host IP] [all|gateway|mcp|ui|adapter])" >&2
      exit 1
      ;;
  esac
done
if [[ -z "${LAN_HOST}" && -n "${OFDD_LAN_HOST:-}" ]]; then
  LAN_HOST="${OFDD_LAN_HOST}"
fi
if [[ -n "${LAN_HOST}" ]]; then
  export OFDD_BRIDGE_URL="http://${LAN_HOST}:8765"
  export OFDD_MCP_OFDD_API_URL="${OFDD_BRIDGE_URL}"
  export OFDD_UI_PUBLIC_BASE="http://${LAN_HOST}:5173"
  export OFDD_MCP_REST_BASE="http://${LAN_HOST}:8090"
  export OFDD_BRIDGE_HOST="0.0.0.0"
  export OFDD_MCP_LISTEN_HOST="0.0.0.0"
  export OFDD_CORS_ALLOW_PRIVATE_LAN="1"
  echo "LAN dashboard: URLs use ${LAN_HOST}; gateway+MCP listen on 0.0.0.0; Vite --host 0.0.0.0. Open firewall TCP 8765, 8090, 5173 if other hosts connect."
fi

BRIDGE_URL="${OFDD_BRIDGE_URL:-http://127.0.0.1:8765}"
# Match start-local.ps1 / gateway: avoid double slashes when joining paths.
BRIDGE_URL="${BRIDGE_URL%/}"
SYNC_INTERVAL="${OFDD_TTL_SYNC_INTERVAL_SECONDS:-5}"

if [[ -n "${LAN_HOST}" ]]; then
  UI_DEV_CMD=(npm run dev -- --host 0.0.0.0)
else
  UI_DEV_CMD=(npm run dev)
fi

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

# Regenerate MCP RAG chunks from docs/ so open-fdd-mcp-rag loads fresh rag_index.json on each start (opt out with OFDD_SKIP_MCP_INDEX_BUILD=1).
refresh_mcp_rag_index() {
  if [[ "${OFDD_SKIP_MCP_INDEX_BUILD:-0}" == "1" ]]; then
    echo "Skipping MCP RAG index rebuild (OFDD_SKIP_MCP_INDEX_BUILD=1)."
    return 0
  fi
  if ! command -v python3 >/dev/null 2>&1; then
    echo "WARNING: python3 not found; skipping MCP index rebuild." >&2
    return 0
  fi
  (
    cd "${REPO_ROOT}"
    python3 scripts/build_mcp_rag_index.py --output stack/mcp-rag/index/rag_index.json
  ) || echo "WARNING: MCP RAG index build failed; search_docs may be stale or empty until you fix errors and restart MCP." >&2
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
_openclaw_url="${OFDD_OPENCLAW_GATEWAY_URL:-${OFDD_CLAW_GATEWAY_URL:-http://127.0.0.1:18789}}"
export OFDD_OPENCLAW_GATEWAY_URL="${_openclaw_url%/}"
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
    refresh_mcp_rag_index
    (
      cd "${REPO_ROOT}"
      start_bg "gateway" open-fdd-gateway
      start_bg "mcp-rag" open-fdd-mcp-rag
    )
    (
      cd "${DESKTOP_UI_DIR}"
      start_bg "desktop-ui" "${UI_DEV_CMD[@]}"
    )
    echo "All services launched with repo-local data defaults."
    printf '%s\n' 'Tip: This run rebuilt stack/mcp-rag/index/rag_index.json (unless OFDD_SKIP_MCP_INDEX_BUILD=1). Re-running without stopping old gateway/mcp/ui processes can leave ports 8765, 8090, or 5173 busy — close old jobs first — see docs/howto/desktop_app.md (Restarting start-local and MCP).'
    echo ""
    echo "Open-FDD UI:        ${OFDD_UI_PUBLIC_BASE}"
    echo "Open-FDD agent API: ${BRIDGE_URL}/openfdd-agent/context  (POST .../openfdd-agent/chat)"
    echo "MCP RAG REST:       ${OFDD_MCP_REST_BASE}/manifest"
    printf 'Plots (FDD-ready):  %s/plots?fdd=1&skipMissing=1&runSource=csv\n' "${OFDD_UI_PUBLIC_BASE}"
    printf '  Add site_id=<uuid> after you ingest (see GET %s/assistant/readiness) for one-click overlay.\n' "${BRIDGE_URL}"
    echo "Bridge health:      ${BRIDGE_URL}/health"
    echo "OpenClaw gateway:   ${OFDD_OPENCLAW_GATEWAY_URL}/health"
    if [[ -n "${OFDD_OPENCLAW_GATEWAY_TOKEN:-${OFDD_CLAW_GATEWAY_TOKEN:-}}" ]]; then
      echo "OpenClaw token set: true"
    else
      echo "OpenClaw token set: false"
    fi
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
    if command -v curl >/dev/null 2>&1; then
      if curl -sf "${OFDD_MCP_REST_BASE}/health" >/dev/null 2>&1; then
        echo "MCP responded OK at ${OFDD_MCP_REST_BASE}/health."
      else
        echo "WARNING: MCP did not respond at ${OFDD_MCP_REST_BASE}/health. Check ${LOG_DIR}/mcp-rag.log"
      fi
      if curl -sf "${OFDD_UI_PUBLIC_BASE}" >/dev/null 2>&1; then
        echo "UI responded OK at ${OFDD_UI_PUBLIC_BASE}."
      else
        echo "WARNING: UI did not respond at ${OFDD_UI_PUBLIC_BASE}. Check ${LOG_DIR}/desktop-ui.log"
      fi
      if curl -sf "${OFDD_OPENCLAW_GATEWAY_URL}/health" >/dev/null 2>&1; then
        echo "OpenClaw gateway responded OK at ${OFDD_OPENCLAW_GATEWAY_URL}/health."
      else
        echo "WARNING: OpenClaw gateway not reachable at ${OFDD_OPENCLAW_GATEWAY_URL}/health (optional unless using /assistant/data-model-openclaw)."
      fi
    fi
    ;;
  gateway)
    write_openfdd_agent_bootstrap "gateway"
    cd "${REPO_ROOT}"
    exec open-fdd-gateway
    ;;
  mcp)
    write_openfdd_agent_bootstrap "mcp"
    refresh_mcp_rag_index
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
    exec "${UI_DEV_CMD[@]}"
    ;;
  *)
    echo "Unknown role '${ROLE}'. Use: all|gateway|mcp|adapter|ui" >&2
    exit 1
    ;;
esac
