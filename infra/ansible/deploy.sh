#!/usr/bin/env bash
# Deploy Open-FDD edge stack — component targets or full stack.
#
#   ./deploy.sh help
#   ./deploy.sh ui --limit acme_vm_bbartling
#   ./deploy.sh backend --limit bacnet_pi
#   ./deploy.sh all --limit acme_vm_bbartling -v
#   export SSHPASS='...' && ./deploy.sh drivers --limit acme_vm_bbartling
#
# Legacy (full deploy): ./deploy.sh --limit bacnet_pi
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$DIR/../.." && pwd)"
cd "$DIR"

INV="${ANSIBLE_INVENTORY:-${DIR}/inventory.yml}"

if [[ -x "${DIR}/../../.ansible_venv/bin/ansible-playbook" ]]; then
  APB="${DIR}/../../.ansible_venv/bin/ansible-playbook"
elif [[ -x "${DIR}/../.ansible_venv/bin/ansible-playbook" ]]; then
  APB="${DIR}/../.ansible_venv/bin/ansible-playbook"
elif command -v ansible-playbook >/dev/null; then
  APB="$(command -v ansible-playbook)"
else
  echo "No ansible-playbook. Create venv: python3 -m venv .ansible_venv && .ansible_venv/bin/pip install ansible-core" >&2
  exit 1
fi

NO_ASK_PASS=false
COMPONENT=""
PLAYBOOK="deploy.yml"
TAGS=""
NEEDS_UI=false
RUN_POST_CHECK="${RUN_POST_CHECK:-1}"
ANSIBLE_EXTRA=()

usage() {
  cat <<'EOF'
Open-FDD edge deploy (infra/ansible)

Usage:
  ./deploy.sh <component> [--limit HOST] [-v] [-e key=val ...]
  ./deploy.sh --limit HOST              # same as: all --limit HOST

Components:
  all         Full stack (code, UI, drivers, systemd, Caddy, MCP, verify)
  ui | web    Built React dashboard only (workspace/api/static/app)
  backend     Bridge API (workspace/api) + bridge systemd + pip deps
  core        open_fdd Python package + editable install
  drivers     BACnet toolshed, poll/commission units, points.csv, commission.env
  data        workspace/data (models, rules store paths — not live historian)
  config      auth.env.local, bridge secrets, Caddyfile
  caddy       Caddy install + TLS + reverse proxy only
  systemd     Reload unit files and restart/enable services (no code sync)
  pip         Re-run venv + pip installs only
  commission  Push points.csv from edge_backup only
  mcp | ai    MCP RAG sidecar (+ edge_ai_stack.yml); ai also runs Ollama bootstrap
  os          apt update + safe upgrade (os_update.yml; -e os_upgrade_reboot=true)
  check       Post-deploy insurance probes only (no file sync)

Examples:
  ./scripts/build_and_test.sh && ./deploy.sh ui --limit acme_vm_bbartling
  ./deploy.sh backend --limit acme_vm_bbartling
  ./deploy.sh drivers --limit acme_vm_bbartling -e enable_bacnet_poll_driver=true
  export SSHPASS='...' && ./deploy.sh all --limit acme_vm_bbartling -v
  ./deploy.sh os --limit acme_vm_bbartling -e os_upgrade_reboot=true

Env:
  SSHPASS              Password for sshpass (optional)
  ANSIBLE_INVENTORY    Default: infra/ansible/inventory.yml
  RUN_POST_CHECK=0     Skip post_deploy_check.sh after deploy
EOF
}

require_ui_build() {
  if [[ ! -f "${ROOT}/workspace/api/static/app/index.html" ]]; then
    echo "Missing compiled dashboard — run one of:" >&2
    echo "  ${ROOT}/scripts/build_operator_dashboard.sh prod" >&2
    echo "  ${ROOT}/scripts/build_and_test.sh" >&2
    exit 1
  fi
}

is_component() {
  case "$1" in
    help|-h|--help) return 0 ;;
    all|ui|web|backend|core|drivers|data|config|caddy|systemd|pip|commission|mcp|ai|os|check) return 0 ;;
    *) return 1 ;;
  esac
}

parse_component() {
  if [[ $# -eq 0 ]]; then
    COMPONENT="all"
    NEEDS_UI=true
    return
  fi
  if is_component "$1"; then
    COMPONENT="$1"
    shift
    case "$COMPONENT" in
      help|-h|--help) usage; exit 0 ;;
      ui|web|all) NEEDS_UI=true ;;
    esac
    return
  fi
  if [[ "$1" == --* ]]; then
    COMPONENT="all"
    NEEDS_UI=true
    return
  fi
  echo "Unknown component: $1" >&2
  echo "Run: ./deploy.sh help" >&2
  exit 1
}

parse_component "$@"
# parse_component shifts only inside the function; drop component from caller "$@" too.
if [[ $# -gt 0 ]] && [[ "$1" == "$COMPONENT" ]]; then
  shift
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --no-ask-pass) NO_ASK_PASS=true; shift ;;
    *) ANSIBLE_EXTRA+=("$1"); shift ;;
  esac
done

case "$COMPONENT" in
  all) TAGS="" ;;
  ui|web) TAGS="preflight,ui" ;;
  backend) TAGS="preflight,backend,pip,systemd" ;;
  core) TAGS="preflight,core,pip" ;;
  drivers) TAGS="preflight,drivers,pip,systemd" ;;
  data) TAGS="preflight,data" ;;
  config) TAGS="preflight,config,caddy" ;;
  caddy) TAGS="caddy,systemd" ;;
  systemd) TAGS="systemd" ;;
  pip) TAGS="preflight,pip" ;;
  commission) TAGS="preflight,commission" ;;
  mcp) TAGS="mcp"; PLAYBOOK="edge_ai_stack.yml" ;;
  ai)
    TAGS=""
    PLAYBOOK=""
    ;;
  os)
    TAGS=""
    PLAYBOOK="os_update.yml"
    RUN_POST_CHECK=0
    ;;
  check)
    TAGS="verify"
    PLAYBOOK="post_deploy_check.yml"
    RUN_POST_CHECK=0
    ;;
esac

if [[ "$NEEDS_UI" == true ]]; then
  require_ui_build
fi

run_playbook() {
  local pb="$1"
  shift
  local -a cmd=("$APB" -i "$INV" "$pb")
  if [[ -n "${TAGS}" ]]; then
    cmd+=(--tags "$TAGS")
  fi
  if [[ -n "${SSHPASS:-}" ]] && command -v sshpass >/dev/null; then
    export SSHPASS
    export ANSIBLE_SSH_PASS="$SSHPASS"
    export ANSIBLE_BECOME_PASS="${ANSIBLE_BECOME_PASS:-$SSHPASS}"
    cmd+=(-e "ansible_ssh_pass=${SSHPASS}" -e "ansible_become_pass=${SSHPASS}")
    sshpass -e "${cmd[@]}" "$@" "${ANSIBLE_EXTRA[@]}"
  elif [[ "$NO_ASK_PASS" == true ]]; then
    "${cmd[@]}" "$@" "${ANSIBLE_EXTRA[@]}"
  else
    "${cmd[@]}" --ask-pass --ask-become-pass "$@" "${ANSIBLE_EXTRA[@]}"
  fi
}

echo "==> Deploy component: ${COMPONENT}${TAGS:+ (tags: ${TAGS})}"

if [[ "$COMPONENT" == "ai" ]]; then
  run_playbook ollama_bootstrap.yml "${ANSIBLE_EXTRA[@]}"
  run_playbook edge_ai_stack.yml "${ANSIBLE_EXTRA[@]}"
  PLAYBOOK=""
fi

if [[ -n "$PLAYBOOK" ]]; then
  run_playbook "$PLAYBOOK"
fi

case "$COMPONENT" in
  all|ui|web|backend|core|drivers|ai) ;;
  *) RUN_POST_CHECK=0 ;;
esac

CHECK_SCRIPT="${DIR}/scripts/post_deploy_check.sh"
chmod +x "$CHECK_SCRIPT" 2>/dev/null || true
if [[ "${RUN_POST_CHECK}" != "0" && -x "$CHECK_SCRIPT" && "$COMPONENT" != "os" ]]; then
  LIMIT_HOST=""
  for ((i = 0; i < ${#ANSIBLE_EXTRA[@]}; i++)); do
    if [[ "${ANSIBLE_EXTRA[i]}" == "--limit" && $((i + 1)) -lt ${#ANSIBLE_EXTRA[@]} ]]; then
      LIMIT_HOST="${ANSIBLE_EXTRA[i + 1]}"
      break
    fi
  done
  if [[ -n "$LIMIT_HOST" ]]; then
    echo ""
    echo "Running post-deploy insurance check (--limit ${LIMIT_HOST})..."
    "$CHECK_SCRIPT" --inventory "$INV" --limit "$LIMIT_HOST"
  fi
fi
