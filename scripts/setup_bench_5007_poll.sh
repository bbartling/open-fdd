#!/usr/bin/env bash
# Enable 1-minute BACnet poll on bench device 5007 and start commission agent.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
VENV="${ROOT}/.venv"
export OPENFDD_REPO_ROOT="$ROOT"
export OPENFDD_WORKSPACE_DIR="${ROOT}/workspace"
export OFDD_DESKTOP_DATA_DIR="${ROOT}/workspace/data"
export PYTHONPATH="${ROOT}/workspace/api:${ROOT}"

"${VENV}/bin/python" - <<'PY'
from openfdd_bridge.bench_b5007_poll import enable_bench_5007_poll
import json
print(json.dumps(enable_bench_5007_poll(poll_interval_s=60, start_commission=True), indent=2))
PY
