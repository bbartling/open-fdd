#!/usr/bin/env bash
# Maintainer-local security audits (parity with CI operator-bridge-security job).
#
#   ./scripts/security/run_maintainer_audits.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

section() {
  echo ""
  echo "==> $1"
}

VENV="/tmp/ofdd-audit-venv"
python3 -m venv "$VENV"
"${VENV}/bin/pip" install -q --upgrade pip pip-audit bandit

section "pip-audit (bridge + bacnet + security constraints)"
"${VENV}/bin/pip" install -q -r docker/python-security-constraints.txt
"${VENV}/bin/pip" install -q -r workspace/api/requirements.txt -r bacnet_toolshed/requirements.txt
"${VENV}/bin/pip-audit"

section "bandit (bridge, high severity)"
"${VENV}/bin/bandit" -r workspace/api/openfdd_bridge -lll -q

section "npm audit (dashboard, high+)"
(cd workspace/dashboard && npm ci && npm audit --audit-level=high)

section "optional: semgrep (install if missing)"
if python3 -m pip show semgrep >/dev/null 2>&1; then
  semgrep scan --config p/default --severity ERROR workspace/api/openfdd_bridge workspace/dashboard/src
else
  echo "semgrep not installed — CI installs it automatically"
fi

echo ""
echo "Maintainer audits complete."
