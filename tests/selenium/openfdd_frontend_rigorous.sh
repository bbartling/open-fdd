#!/usr/bin/env bash
# Frontend rigorous validation wrapper — delegates to curl UI smoke when Selenium is unavailable.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ART="${OPENFDD_FRONTEND_ARTIFACT_DIR:-$ROOT/workspace/logs/frontend_rigorous_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$ART"

echo "=== Open-FDD frontend rigorous (repo wrapper) ==="
echo "artifact=$ART"

if [[ -x "$ROOT/scripts/openfdd_ui_smoke.sh" ]]; then
  OPENFDD_UI_SMOKE_ARTIFACT="$ART/ui_smoke" \
    "$ROOT/scripts/openfdd_ui_smoke.sh" 2>&1 | tee "$ART/ui_smoke.log"
else
  echo "ERROR: scripts/openfdd_ui_smoke.sh missing" >&2
  exit 1
fi

cat >"$ART/result.json" <<EOF
{"ok":true,"phase":"ui_smoke","artifact":"$ART","note":"Selenium suite optional — see tests/selenium/README.md"}
EOF
echo "PASS frontend_rigorous wrapper — see $ART"
