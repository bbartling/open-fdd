#!/usr/bin/env bash
# Soft-OPEN 371 T0c/T3d — product smoke Soft-OPEN gate wrapper.
# Requires OPENFDD_EXPECTED_REVISION. Dual-site default: BUILDING_100,ACME.
# Exit: 0 PASS · 2 FAIL · 3 BLOCKED · 4 VERSION_MISMATCH
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="${OPENFDD_PRODUCT_SMOKE_PY:-$ROOT/scripts/gates/product_smoke_softopen.py}"
ART="${OPENFDD_PRODUCT_SMOKE_ART:-$ROOT/reports/product_smoke_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$ART"
: "${OPENFDD_EXPECTED_REVISION:?OPENFDD_EXPECTED_REVISION required}"
export OPENFDD_PRODUCT_SMOKE_ART="$ART"
set +e
python3 "$PY" --artifact-dir "$ART" "$@"
RC=$?
set -e
echo "product_smoke_softopen rc=$RC art=$ART"
if [[ -f "$ART/SUMMARY.json" ]]; then
  python3 -c 'import json,sys; print("verdict="+json.load(open(sys.argv[1]))["verdict"])' "$ART/SUMMARY.json"
fi
exit "$RC"
