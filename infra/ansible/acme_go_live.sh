#!/usr/bin/env bash
# Acme vm-bbartling go-live: commission temp points → deploy stack → enable 60s poll.
#
#   export SSHPASS='...'
#   ./acme_go_live.sh --limit acme_vm_bbartling [-v]
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

LIMIT=""
EXTRA=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --limit|-l) LIMIT="$2"; shift 2 ;;
    -v|--verbose) EXTRA+=(-v); shift ;;
    *) EXTRA+=("$1"); shift ;;
  esac
done
[[ -n "$LIMIT" ]] || { echo "ERROR: --limit required (acme_vm_bbartling)" >&2; exit 1; }

echo "=== 1/4 Commission GL36 / economizer poll points.csv ==="
"${DIR}/scripts/acme_commission_gl36.sh"

echo ""
echo "=== 2/4 Deploy Open-FDD edge stack ==="
"${DIR}/deploy.sh" all --limit "$LIMIT" "${EXTRA[@]}"

echo ""
echo "=== 3/4 MCP sidecar (Ollama skipped — set ACME_ENABLE_OLLAMA=1 to bootstrap) ==="
if [[ "${ACME_ENABLE_OLLAMA:-}" == "1" ]]; then
  if [[ -n "${SSHPASS:-}" ]] && command -v sshpass >/dev/null; then
    sshpass -e ansible-playbook -i inventory.yml ollama_bootstrap.yml --limit "$LIMIT" \
      -e enable_ollama=true -e ollama_ram_tier=16gb "${EXTRA[@]}"
  else
    ansible-playbook -i inventory.yml ollama_bootstrap.yml --limit "$LIMIT" \
      -e enable_ollama=true -e ollama_ram_tier=16gb "${EXTRA[@]}"
  fi
fi
if [[ -n "${SSHPASS:-}" ]] && command -v sshpass >/dev/null; then
  sshpass -e ansible-playbook -i inventory.yml edge_ai_stack.yml --limit "$LIMIT" "${EXTRA[@]}"
else
  ansible-playbook -i inventory.yml edge_ai_stack.yml --limit "$LIMIT" "${EXTRA[@]}"
fi

echo ""
echo "=== 4/4 Enable BACnet poll driver (60s) ==="
if [[ -n "${SSHPASS:-}" ]] && command -v sshpass >/dev/null; then
  sshpass -e "${DIR}/deploy.sh" drivers --limit "$LIMIT" -e enable_bacnet_poll_driver=true "${EXTRA[@]}"
else
  "${DIR}/deploy.sh" drivers --limit "$LIMIT" -e enable_bacnet_poll_driver=true "${EXTRA[@]}"
fi

HOST="$(ansible-inventory -i inventory.yml --host "$LIMIT" 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin).get("ansible_host",""))' || true)"
echo ""
echo "OK: Acme go-live complete. Dashboard: http://${HOST}/"
