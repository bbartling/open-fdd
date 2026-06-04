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
SECRETS_DIR="${DIR}/secrets"

# Map inventory --limit host → secrets/<alias>.env.local (gitignored).
load_edge_secrets() {
  local limit="${1:-}"
  local secrets_file=""
  if [[ -n "$limit" && -f "${SECRETS_DIR}/${limit}.env.local" ]]; then
    secrets_file="${SECRETS_DIR}/${limit}.env.local"
  else
    case "$limit" in
      acme_vm_bbartling) secrets_file="${SECRETS_DIR}/acme.env.local" ;;
      bacnet_pi) secrets_file="${SECRETS_DIR}/bacnet_pi.env.local" ;;
    esac
  fi
  if [[ -n "$secrets_file" && -f "$secrets_file" ]]; then
    set -a
    # shellcheck source=/dev/null
    source "$secrets_file"
    set +a
    export SSHPASS="${SSHPASS:-}"
  fi
}

resolve_ansible_limit() {
  local prev=""
  for arg in "$@"; do
    if [[ "$prev" == --limit ]]; then
      if [[ -z "$arg" || "$arg" == --* ]]; then
        echo "error: --limit requires a host pattern" >&2
        return 1
      fi
      echo "$arg"
      return 0
    fi
    prev="$arg"
  done
  if [[ "$prev" == --limit ]]; then
    echo "error: --limit requires a host pattern" >&2
    return 1
  fi
}

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
  systemd     Legacy only: reload openfdd-* app units (not used with deploy.sh docker)
  pip         Re-run venv + pip installs only
  commission  Push points.csv from edge_backup only
  mcp | ai    MCP RAG sidecar (+ edge_ai_stack.yml); ai also runs Ollama bootstrap
  os          apt update + safe upgrade (os_update.yml; -e os_upgrade_reboot=true)
  check       Post-deploy insurance probes only (no file sync)
  docker      Docker Compose (default: pull ghcr.io/bbartling/* — set OPENFDD_IMAGE_TAG)
  maintain    Safe Docker prune on edge only (images/networks/containers; never volumes)
  ops         Full Docker deploy + maintenance + TTL sync + SPARQL/feather/log health (edge_operational_sync.yml)

Examples:
  OPENFDD_IMAGE_TAG=2026.06.04-edge ./deploy.sh docker --limit acme_vm_bbartling
  ./scripts/build_and_test.sh && ./deploy.sh ui --limit acme_vm_bbartling
  ./deploy.sh backend --limit acme_vm_bbartling
  ./deploy.sh drivers --limit acme_vm_bbartling -e enable_bacnet_poll_driver=true
  export SSHPASS='...' && ./deploy.sh all --limit acme_vm_bbartling -v
  ./deploy.sh os --limit acme_vm_bbartling -e os_upgrade_reboot=true
  ./deploy.sh maintain --limit acme_vm_bbartling
  ./deploy.sh ops --limit acme_vm_bbartling

Env:
  SSHPASS              Password for sshpass (optional; or set in secrets/<host>.env.local)
  ANSIBLE_INVENTORY    Default: infra/ansible/inventory.yml
  RUN_POST_CHECK=0     Skip post_deploy_check.sh after deploy

Secrets (gitignored): infra/ansible/secrets/README.md
  acme_vm_bbartling → secrets/acme.env.local
  bacnet_pi         → secrets/bacnet_pi.env.local
EOF
}

require_docker_deploy() {
  local tag="${OPENFDD_IMAGE_TAG:-}"
  local pull="${OPENFDD_DOCKER_PULL_FROM_GHCR:-1}"
  case "$pull" in
    0|false|no|off) pull=0 ;;
    *) pull=1 ;;
  esac
  if [[ "$pull" == "1" ]]; then
    if [[ -z "$tag" || "$tag" == "local" ]]; then
      echo "GHCR deploy: set OPENFDD_IMAGE_TAG to the tag published by GitHub Actions." >&2
      echo "  Example: OPENFDD_IMAGE_TAG=2026.06.04-edge ./deploy.sh docker --limit acme_vm_bbartling" >&2
      echo "Legacy tar path: OPENFDD_DOCKER_PULL_FROM_GHCR=0 ./scripts/docker_build.sh --save" >&2
      exit 1
    fi
    ANSIBLE_EXTRA+=(-e "openfdd_docker_pull_from_ghcr=true" -e "openfdd_docker_image_tag=${tag}")
    return 0
  fi
  tag="${tag:-local}"
  ANSIBLE_EXTRA+=(-e "openfdd_docker_pull_from_ghcr=false" -e "openfdd_docker_image_tag=${tag}")
  local tar="${ROOT}/docker/dist/openfdd-images-${tag}.tar.gz"
  if [[ ! -f "$tar" ]]; then
    echo "Missing Docker image bundle: $tar" >&2
    echo "Run: OPENFDD_IMAGE_TAG=${tag} ./scripts/docker_build.sh --save" >&2
    echo "Or GHCR: OPENFDD_IMAGE_TAG=yourtag ./deploy.sh docker --limit <host>" >&2
    exit 1
  fi
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
    all|ui|web|backend|core|drivers|data|config|caddy|systemd|pip|commission|mcp|ai|os|check|docker|maintain|ops) return 0 ;;
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

DEPLOY_LIMIT="$(resolve_ansible_limit "${ANSIBLE_EXTRA[@]}")" || exit 1
if [[ -n "$DEPLOY_LIMIT" ]]; then
  load_edge_secrets "$DEPLOY_LIMIT"
fi

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
  docker)
    PLAYBOOK="deploy_docker.yml"
    TAGS=""
    ;;
  maintain)
    PLAYBOOK="edge_docker_maintenance.yml"
    TAGS=""
    RUN_POST_CHECK=0
    ;;
  ops)
    PLAYBOOK="edge_operational_sync.yml"
    TAGS=""
    ;;
esac

if [[ "$COMPONENT" == "docker" || "$COMPONENT" == "ops" ]]; then
  require_docker_deploy
fi

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
  all|ui|web|backend|core|drivers|ai|docker|maintain|ops) ;;
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
    load_edge_secrets "$LIMIT_HOST"
    "$CHECK_SCRIPT" --inventory "$INV" --limit "$LIMIT_HOST"
  fi
fi
