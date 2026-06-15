#!/usr/bin/env bash
# Dual-source bench smoke: BACnet 5007 + Niagara bench9065 + optional DataFusion SQL.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export OPENFDD_BASE_URL="${OPENFDD_BASE_URL:-http://127.0.0.1:8765}"
export OPENFDD_AUTH_ENV="${OPENFDD_AUTH_ENV:-workspace/auth.env.local}"

echo "==> Core bench smoke (BACnet + Niagara + FDD batch)"
python3 scripts/smoke_benserver_bench.py "$@"

echo ""
echo "==> DataFusion SQL lab preview (optional extra)"
if ! python3 -c "import datafusion" 2>/dev/null; then
  echo "  SKIP datafusion not installed — pip install -e '.[datafusion]'"
  exit 0
fi

AUTH="$ROOT/workspace/auth.env.local"
if [[ -f "$AUTH" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$AUTH"
  set +a
fi
USER="${OFDD_INTEGRATOR_USER:-integrator}"
PASS="${OFDD_INTEGRATOR_PASSWORD:-changeme}"
TOKEN=$(curl -sS -X POST "$OPENFDD_BASE_URL/api/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"$USER\",\"password\":\"$PASS\"}" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("token",""))')

if [[ -z "$TOKEN" ]]; then
  echo "  FAIL login for DataFusion smoke"
  exit 1
fi

BODY='{"backend":"datafusion_sql","sql":"SELECT *, \"duct-t\" > 80.0 AS fault FROM telemetry","limit":200}'
RES=$(curl -sS -X POST "$OPENFDD_BASE_URL/api/rules/lab/preview" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d "$BODY")
OK=$(echo "$RES" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("ok"))')
if [[ "$OK" == "True" ]]; then
  echo "  OK   DataFusion SQL preview on duct-t"
else
  echo "  FAIL DataFusion preview: $RES"
  exit 1
fi

echo ""
echo "Dual source smoke PASS (core + DataFusion)"
