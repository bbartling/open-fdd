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

PASS_EXTRA=()
if [[ -n "${SSHPASS:-}" ]] && command -v sshpass >/dev/null; then
  export ANSIBLE_SSH_PASS="$SSHPASS"
  export ANSIBLE_BECOME_PASS="${ANSIBLE_BECOME_PASS:-$SSHPASS}"
  PASS_EXTRA=(
    -e "ansible_ssh_pass=${SSHPASS}"
    -e "ansible_become_pass=${SSHPASS}"
    -e "ansible_ssh_common_args=-o StrictHostKeyChecking=no"
  )
elif [[ "$NO_ASK_PASS" == true ]]; then
  :
else
  PASS_EXTRA=(--ask-pass --ask-become-pass)
fi

exec "$APB" -i "$INV" deploy.yml "${PASS_EXTRA[@]}" "${EXTRA[@]}"
