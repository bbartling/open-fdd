#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="${ROOT}:${PYTHONPATH:-}"
exec python3 "$ROOT/scripts/run_central_api.py" "$@"
