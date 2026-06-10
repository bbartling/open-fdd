#!/usr/bin/env bash
# Open-FDD edge orchestration — container pull + health checks (no application file deploy).
#
#   ./deploy.sh help
#   OPENFDD_IMAGE_TAG=latest ./deploy.sh docker --limit acme_vm_bbartling
#   ./deploy.sh check --limit acme_vm_bbartling
#
# Application code ships in GHCR images. Ansible does not rsync Python, React, rules, or models.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$DIR/../.." && pwd)"
cd "$DIR"

INV="${ANSIBLE_INVENTORY:-${DIR}/inventory.yml}"
SECRETS_DIR="${DIR}/secrets"

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
PLAYBOOK="deploy_docker.yml"
TAGS=""
RUN_POST_CHECK="${RUN_POST_CHECK:-1}"
ANSIBLE_EXTRA=()

LEGACY_COMPONENTS="all ui web backend core drivers data config caddy systemd pip commission mcp ai ollama"

usage() {
  cat <<'EOF'
Open-FDD edge deploy (infra/ansible)

Open-FDD deployment is container-based. Ansible does not deploy application files.
Ansible orchestrates GHCR image pull, docker compose up, host Caddy/timers, and health checks.

Usage:
  ./deploy.sh <component> [--limit HOST] [-v] [-e key=val ...]

Primary commands:
  docker      Pull ghcr.io/bbartling/* and docker compose up -d (default path)
  check       Post-deploy health probes only (no mutations)
  maintain    Safe Docker prune on edge (never volumes)
  ops         docker + maintenance + API TTL sync probes (edge_operational_sync.yml)
  os          apt update + safe upgrade (os_update.yml)
  logs        (use: docker compose logs on edge, or scripts/post_deploy_check.sh)
  help        This message

Examples:
  OPENFDD_IMAGE_TAG=latest ./deploy.sh docker --limit acme_vm_bbartling
  OPENFDD_IMAGE_TAG=latest ./scripts/upgrade_edge_ghcr.sh --limit acme_vm_bbartling
  ./deploy.sh check --limit acme_vm_bbartling
  ./deploy.sh maintain --limit acme_vm_bbartling

Optional one-time bootstrap (deprecated file push — prefer API import):
  ./deploy.sh docker --limit acme_vm_bbartling \
    -e openfdd_push_site_pack=true \
    -e openfdd_push_bacnet_config=true

Legacy workstation rsync (lab Pi only): see legacy/README.md
  export OPENFDD_ALLOW_LEGACY_DEPLOY=1

Env:
  OPENFDD_IMAGE_TAG     GHCR tag (default in host_vars: latest)
  SSHPASS               From secrets/<host>.env.local when using --limit
  RUN_POST_CHECK=0      Skip post_deploy_check.sh after deploy
  ANSIBLE_INVENTORY     Default: infra/ansible/inventory.yml

Secrets: infra/ansible/secrets/README.md
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
      tag="${tag:-latest}"
    fi
    ANSIBLE_EXTRA+=(-e "openfdd_docker_pull_from_ghcr=true" -e "openfdd_docker_image_tag=${tag}")
    return 0
  fi
  tag="${tag:-local}"
  ANSIBLE_EXTRA+=(-e "openfdd_docker_pull_from_ghcr=false" -e "openfdd_docker_image_tag=${tag}")
  local tar="${ROOT}/docker/dist/openfdd-images-${tag}.tar.gz"
  if [[ ! -f "$tar" ]]; then
    echo "Missing Docker image bundle: $tar" >&2
    echo "Prefer GHCR: OPENFDD_IMAGE_TAG=latest ./deploy.sh docker --limit <host>" >&2
    exit 1
  fi
}

legacy_blocked() {
  echo "Component '$1' uses removed workstation file deploy." >&2
  echo "  Use: OPENFDD_IMAGE_TAG=latest ./deploy.sh docker --limit <host>" >&2
  echo "  Models/rules: HTTPS API (commissioning-import, rules/save) — not rsync." >&2
  exit 1
}

is_component() {
  case "$1" in
    help|-h|--help|docker|check|maintain|ops|os|logs) return 0 ;;
    all|ui|web|backend|core|drivers|data|config|caddy|systemd|pip|commission|mcp|ai|ollama) return 0 ;;
    *) return 1 ;;
  esac
}

parse_component() {
  if [[ $# -eq 0 ]]; then
    COMPONENT="docker"
    return
  fi
  if is_component "$1"; then
    COMPONENT="$1"
    shift
    return
  fi
  if [[ "$1" == --* ]]; then
    COMPONENT="docker"
    return
  fi
  echo "Unknown component: $1" >&2
  echo "Run: ./deploy.sh help" >&2
  exit 1
}

parse_component "$@"
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
  help|-h|--help) usage; exit 0 ;;
  logs)
    echo "On edge: docker compose -f ~/open-fdd/docker-compose.yml logs -f bridge commission"
    exit 0
    ;;
  docker) PLAYBOOK="deploy_docker.yml"; TAGS="" ;;
  check) PLAYBOOK="post_deploy_check.yml"; TAGS="verify"; RUN_POST_CHECK=0 ;;
  maintain) PLAYBOOK="edge_docker_maintenance.yml"; TAGS=""; RUN_POST_CHECK=0 ;;
  ops) PLAYBOOK="edge_operational_sync.yml"; TAGS="" ;;
  os) PLAYBOOK="os_update.yml"; TAGS=""; RUN_POST_CHECK=0 ;;
  all|ui|web|backend|core|drivers|data|config|caddy|systemd|pip|commission|mcp|ai|ollama)
    legacy_blocked "$COMPONENT"
    ;;
  *)
    echo "Unknown component: $COMPONENT" >&2
    exit 1
    ;;
esac

if [[ "$COMPONENT" == "docker" || "$COMPONENT" == "ops" ]]; then
  require_docker_deploy
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

if [[ "$COMPONENT" == "ai" && "${OPENFDD_ALLOW_LEGACY_DEPLOY:-}" == "1" ]]; then
  run_playbook ollama_bootstrap.yml "${ANSIBLE_EXTRA[@]}"
  run_playbook edge_ai_stack.yml "${ANSIBLE_EXTRA[@]}"
  PLAYBOOK=""
fi

if [[ -n "$PLAYBOOK" ]]; then
  run_playbook "$PLAYBOOK"
fi

case "$COMPONENT" in
  docker|maintain|ops) ;;
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
