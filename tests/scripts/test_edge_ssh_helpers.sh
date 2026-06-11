#!/usr/bin/env bash
# edge_ssh_helpers — password auth opts when SSHPASS is set.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HELPERS="${ROOT}/infra/ansible/scripts/edge_ssh_helpers.sh"
# shellcheck source=/dev/null
source "$HELPERS"

unset SSHPASS
build_edge_ssh_cmd
[[ "${EDGE_SSH_CMD[0]}" == "ssh" ]] || { echo "expected ssh without SSHPASS"; exit 1; }

export SSHPASS=test
if command -v sshpass >/dev/null 2>&1; then
  build_edge_ssh_cmd
  joined="${EDGE_SSH_PASS_CMD[*]}"
  [[ "$joined" == *PreferredAuthentications=password* ]] || { echo "missing password auth opt: $joined"; exit 1; }
  [[ "$joined" == *PubkeyAuthentication=no* ]] || { echo "missing PubkeyAuthentication=no: $joined"; exit 1; }
fi

echo "edge_ssh_helpers ok"
