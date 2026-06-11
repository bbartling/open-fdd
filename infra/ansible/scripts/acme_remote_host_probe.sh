#!/usr/bin/env bash
# Read-only remote host/container probe for Acme edge (via SSH).
#
#   ./infra/ansible/scripts/acme_remote_host_probe.sh --limit acme_vm_bbartling --json-out /tmp/host.json
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
ANSIBLE_DIR="$(cd "$DIR/.." && pwd)"
SECRETS="${ANSIBLE_DIR}/secrets/acme.env.local"
PROBE_PY="${DIR}/acme_remote_host_probe.py"

LIMIT=""
JSON_OUT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --limit) LIMIT="$2"; shift 2 ;;
    --json-out) JSON_OUT="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,5p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown: $1" >&2; exit 1 ;;
  esac
done

[[ -n "$LIMIT" ]] || { echo "Need --limit" >&2; exit 1; }

if [[ -f "$SECRETS" ]]; then
  set +u
  # shellcheck disable=SC1090
  set -a && source "$SECRETS" && set +a
  set -u
fi

SSH_USER="${ACME_SSH_USER:-ben}"
SSH_HOST="${ACME_SSH_HOST:-}"
if [[ -z "$SSH_HOST" ]]; then
  echo '{"error":"ACME_SSH_HOST not configured"}' >"${JSON_OUT:-/dev/stdout}"
  exit 1
fi

# shellcheck source=edge_ssh_helpers.sh
source "${DIR}/edge_ssh_helpers.sh"
EDGE_SSH_CONNECT_TIMEOUT=12
build_edge_ssh_cmd
target="${SSH_USER}@${SSH_HOST}"
ssh_cmd=("${EDGE_SSH_CMD[@]}")
if ! "${EDGE_SSH_CMD[@]}" "$target" true 2>/dev/null && [[ ${#EDGE_SSH_PASS_CMD[@]} -gt 0 ]]; then
  ssh_cmd=("${EDGE_SSH_PASS_CMD[@]}")
fi
RAW="$("${ssh_cmd[@]}" "$target" python3 - <"$PROBE_PY")"

if [[ -n "$JSON_OUT" ]]; then
  printf '%s\n' "$RAW" >"$JSON_OUT"
else
  printf '%s\n' "$RAW"
fi
