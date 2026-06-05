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

echo "==> Build React dashboard (vitest + ship to workspace/api/static/app)"
chmod +x scripts/build_operator_dashboard.sh
./scripts/build_operator_dashboard.sh test

echo "==> Bridge API tests"
export OPENFDD_REPO_ROOT="$ROOT"
export OPENFDD_WORKSPACE_DIR="${ROOT}/workspace"
export OFDD_DESKTOP_DATA_DIR="${ROOT}/workspace/data"
export PYTHONPATH="$ROOT:${ROOT}/workspace/api"
# Isolated data dir when workspace/data/model.json is root-owned after docker deploy
TEST_DATA="${ROOT}/.build_test_data"
mkdir -p "$TEST_DATA"
if [[ ! -r "${ROOT}/workspace/data/model.json" ]]; then
  cp "${ROOT}/workspace/data/bench_import_model.json" "$TEST_DATA/model.json" 2>/dev/null \
    || echo '{"sites":[],"equipment":[],"points":[]}' >"$TEST_DATA/model.json"
else
  cp "${ROOT}/workspace/data/model.json" "$TEST_DATA/model.json" 2>/dev/null \
    || cp "${ROOT}/workspace/data/bench_import_model.json" "$TEST_DATA/model.json" 2>/dev/null \
    || echo '{"sites":[],"equipment":[],"points":[]}' >"$TEST_DATA/model.json"
fi
export OFDD_DESKTOP_DATA_DIR="$TEST_DATA"
# Inherit no credentials from workspace/auth.env.local — tests expect auth off unless they reload the app.
unset OFDD_AUTH_SECRET OFDD_OPERATOR_USER OFDD_OPERATOR_PASSWORD \
  OFDD_INTEGRATOR_USER OFDD_INTEGRATOR_PASSWORD OFDD_AGENT_USER OFDD_AGENT_PASSWORD \
  OFDD_WEB_USER OFDD_WEB_PASSWORD 2>/dev/null || true
"${VENV}/bin/pytest" open_fdd/tests/arrow_runtime open_fdd/tests/playground tests/bacnet_toolshed/ tests/workspace_bridge/ -q

echo "==> Smoke: compiled SPA present"
test -f workspace/api/static/app/index.html

echo "==> Supervisor manifest vs Dockerfile"
chmod +x scripts/validate_supervisor_manifest.sh
./scripts/validate_supervisor_manifest.sh

echo ""
echo "OK — build and tests passed. Next:"
echo "  ./scripts/openfdd_stack.sh up      # Docker supervisor dev stack"
echo "  ./scripts/run_local.sh restart     # legacy host units (see workspace/deploy/README.md)"
echo "  cd infra/ansible && ./deploy.sh docker --limit <host>"
