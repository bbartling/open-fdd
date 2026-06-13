#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
source "$ROOT/scripts/lib/free_port.sh"

PORT="${OPENFDD_CENTRAL_API_PORT:-8060}"
free_port "$PORT" "OpenFDD RCx Central API"

export PYTHONPATH="${ROOT}:${PYTHONPATH:-}"
exec python3 "$ROOT/scripts/run_central_api.py" "$@"
