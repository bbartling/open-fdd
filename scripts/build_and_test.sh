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
# test_ollama agent_context needs readable workspace/data/model.json (often root-owned after docker deploy)
"${VENV}/bin/pytest" tests/bacnet_toolshed/ tests/workspace_bridge/ -q \
  --ignore=tests/workspace_bridge/test_ollama.py

echo "==> Smoke: compiled SPA present"
test -f workspace/api/static/app/index.html

echo "==> Supervisor manifest vs Dockerfile"
chmod +x scripts/validate_supervisor_manifest.sh
./scripts/validate_supervisor_manifest.sh

echo ""
echo "OK — build and tests passed. Next:"
echo "  ./scripts/openfdd_stack.sh up      # Docker supervisor dev stack"
echo "  ./scripts/run_local.sh restart     # legacy systemd + Caddy (see workspace/deploy/README.md)"
echo "  cd infra/ansible && ./deploy.sh docker --limit <host>"
