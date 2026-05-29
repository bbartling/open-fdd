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

# Prefer SSH keys. For password auth use sshpass -e (reads SSHPASS env) — never -e ansible_ssh_pass on CLI.
if [[ -n "${SSHPASS:-}" ]] && command -v sshpass >/dev/null; then
  export SSHPASS
  exec sshpass -e "$APB" -i "$INV" deploy.yml "${EXTRA[@]}"
elif [[ "$NO_ASK_PASS" == true ]]; then
  exec "$APB" -i "$INV" deploy.yml "${EXTRA[@]}"
else
  exec "$APB" -i "$INV" deploy.yml --ask-pass --ask-become-pass "${EXTRA[@]}"
fi
