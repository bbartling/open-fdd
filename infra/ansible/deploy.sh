#!/usr/bin/env bash
# Deploy Open-FDD edge stack via Ansible.
# Requires: ./scripts/build_and_test.sh (compiled React in workspace/api/static/app)
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$DIR/../.." && pwd)"
cd "$DIR"

if [[ ! -f "${ROOT}/workspace/api/static/app/index.html" ]]; then
  echo "Missing compiled dashboard — run: ${ROOT}/scripts/build_and_test.sh" >&2
  exit 1
fi
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

EXTRA=()
NO_ASK_PASS=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    --no-ask-pass) NO_ASK_PASS=true; shift ;;
    *) EXTRA+=("$1"); shift ;;
  esac
done

run_playbook() {
  if [[ -n "${SSHPASS:-}" ]] && command -v sshpass >/dev/null; then
    export SSHPASS
    export ANSIBLE_SSH_PASS="$SSHPASS"
    export ANSIBLE_BECOME_PASS="${ANSIBLE_BECOME_PASS:-$SSHPASS}"
    EXTRA+=(-e "ansible_ssh_pass=${SSHPASS}" -e "ansible_become_pass=${SSHPASS}")
    sshpass -e "$APB" -i "$INV" deploy.yml "${EXTRA[@]}"
  elif [[ "$NO_ASK_PASS" == true ]]; then
    "$APB" -i "$INV" deploy.yml "${EXTRA[@]}"
  else
    "$APB" -i "$INV" deploy.yml --ask-pass --ask-become-pass "${EXTRA[@]}"
  fi
}

run_playbook

CHECK_SCRIPT="${DIR}/scripts/post_deploy_check.sh"
chmod +x "$CHECK_SCRIPT" 2>/dev/null || true
if [[ "${RUN_POST_CHECK:-1}" != "0" && -x "$CHECK_SCRIPT" ]]; then
  LIMIT_HOST=""
  for ((i = 0; i < ${#EXTRA[@]}; i++)); do
    if [[ "${EXTRA[i]}" == "--limit" && $((i + 1)) -lt ${#EXTRA[@]} ]]; then
      LIMIT_HOST="${EXTRA[i + 1]}"
      break
    fi
  done
  if [[ -n "$LIMIT_HOST" ]]; then
    echo ""
    echo "Running post-deploy insurance check (--limit ${LIMIT_HOST})..."
    "$CHECK_SCRIPT" --inventory "$INV" --limit "$LIMIT_HOST"
  fi
fi
