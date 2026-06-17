#!/usr/bin/env bash
# Internal worker — invoked by systemd-run or setsid. Do not run from Cursor chat directly.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PYTHON="${ROOT}/.venv/bin/python3"
[[ -x "$PYTHON" ]] || PYTHON="$(command -v python3)"
export OPENFDD_REPO_ROOT="${OPENFDD_REPO_ROOT:-$ROOT}"
export PYTHONPATH="${PYTHONPATH:-$ROOT:$ROOT/workspace/api}"
exec "$PYTHON" "${ROOT}/scripts/smoke_paired_fdd_harness.py" "$@"
