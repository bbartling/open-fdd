#!/usr/bin/env bash
# Host-only bench bootstrap (no Docker) — poll CSV → feather for local UI/dev.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
VENV="${ROOT}/.venv"
export OPENFDD_REPO_ROOT="$ROOT"
export OPENFDD_WORKSPACE_DIR="${ROOT}/workspace"
export OFDD_DESKTOP_DATA_DIR="${ROOT}/workspace/data"
export PYTHONPATH="${ROOT}/workspace/api:${ROOT}"

mkdir -p workspace/bacnet/commissioning workspace/bacnet/polls workspace/data/feather_store
if [[ -f edge_config/demo/bens-office/commission.env ]]; then
  cp edge_config/demo/bens-office/commission.env workspace/bacnet/commissioning/commission.env
fi
"${VENV}/bin/python" scripts/setup_bench_afdd.py
"${VENV}/bin/python" -c "from openfdd_bridge.ttl_service import TtlService; TtlService().sync()"
"${VENV}/bin/python" - <<'PY'
from openfdd_bridge.bench_b5007_poll import enable_bench_5007_poll
import json
print(json.dumps(enable_bench_5007_poll(poll_interval_s=60, start_commission=True), indent=2)[:800])
PY
echo "OK — host bench ready (4x 5007 points @ 60s; run scripts/host_bench_poll_supervisor.py for continuous poll)"
