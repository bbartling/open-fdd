#!/usr/bin/env bash
# Internal pytest worker — systemd/setsid only. Do not run from Cursor chat.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PYTHON="${ROOT}/.venv/bin/python3"
[[ -x "$PYTHON" ]] || PYTHON="$(command -v python3)"
export OPENFDD_REPO_ROOT="${OPENFDD_REPO_ROOT:-$ROOT}"
export OFDD_DESKTOP_DATA_DIR="${OFDD_DESKTOP_DATA_DIR:-$ROOT/workspace/data}"
export PYTHONPATH="${PYTHONPATH:-$ROOT:$ROOT/workspace/api}"
LOG="${1:-/tmp/openfdd_pytest_workspace_bridge.log}"
EXITFILE="${2:-/tmp/openfdd_pytest_workspace_bridge.exitcode}"
set +e
"$PYTHON" -m pytest tests/workspace_bridge -q --tb=no >"$LOG" 2>&1
echo $? >"$EXITFILE"
