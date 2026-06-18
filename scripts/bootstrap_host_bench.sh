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
"${VENV}/bin/python" "${ROOT}/scripts/seed_bench_poll_samples.py"
echo "OK — host bench ready (feather ingested from workspace/bacnet/polls/samples.csv)"
