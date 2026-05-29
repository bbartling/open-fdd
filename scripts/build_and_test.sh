#!/usr/bin/env bash
# Build React dashboard + run bridge tests before edge deploy.
#
#   ./scripts/build_and_test.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VENV="${ROOT}/.venv"
if [[ ! -x "${VENV}/bin/python" ]]; then
  python3 -m venv "$VENV"
fi

echo "==> Python deps"
"${VENV}/bin/pip" install -q -e ".[dev,engine]"
"${VENV}/bin/pip" install -q -r workspace/api/requirements.txt
"${VENV}/bin/pip" install -q -r bacnet_toolshed/requirements.txt 2>/dev/null || true
"${VENV}/bin/pip" install -q httpx 2>/dev/null || true

echo "==> Build React dashboard (ship to workspace/api/static/app)"
chmod +x scripts/build_operator_dashboard.sh
./scripts/build_operator_dashboard.sh

echo "==> Bridge API tests"
export OPENFDD_REPO_ROOT="$ROOT"
export OPENFDD_WORKSPACE_DIR="${ROOT}/workspace"
export OFDD_DESKTOP_DATA_DIR="${ROOT}/workspace/data"
export PYTHONPATH="$ROOT:${ROOT}/workspace/api"
"${VENV}/bin/pytest" tests/bacnet_toolshed/ tests/workspace_bridge/ -q

echo "==> Smoke: compiled SPA present"
test -f workspace/api/static/app/index.html

echo ""
echo "OK — build and tests passed. Next:"
echo "  ./scripts/run_local.sh start     # local edge-like stack on 0.0.0.0:8765"
echo "  cd infra/ansible && ./deploy.sh --limit bacnet_pi -v"
