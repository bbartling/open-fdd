#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
INV="${ANSIBLE_INVENTORY:-${DIR}/inventory.yml}"

if [[ -x "${DIR}/../../.ansible_venv/bin/ansible-playbook" ]]; then
  APB="${DIR}/../../.ansible_venv/bin/ansible-playbook"
elif command -v ansible-playbook >/dev/null; then
  APB="$(command -v ansible-playbook)"
else
  echo "ansible-playbook not found" >&2
  exit 1
fi

LIMIT=""
EXTRA=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --limit|-l) LIMIT="$2"; shift 2 ;;
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
else
  PASS_EXTRA=(--ask-pass --ask-become-pass)
fi

LIMIT_ARG=()
[[ -n "$LIMIT" ]] && LIMIT_ARG=(--limit "$LIMIT")

exec "$APB" -i "$INV" stop_bacnet_polling.yml "${LIMIT_ARG[@]}" "${PASS_EXTRA[@]}" "${EXTRA[@]}"
