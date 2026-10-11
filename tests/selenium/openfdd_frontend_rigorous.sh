#!/usr/bin/env bash
# Soft-OPEN 371 T3e — real Selenium product browser (no curl-only PASS).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ART="${OPENFDD_UI_ARTIFACT_DIR:-$ROOT/reports/product_browser_$(date -u +%Y%m%dT%H%M%SZ)}"
PY="${OPENFDD_PRODUCT_BROWSER_PY:-$ROOT/tests/selenium/openfdd_product_browser.py}"
MANIFEST="${OPENFDD_UI_EXPECTATIONS:-$ROOT/tests/selenium/fixtures/product_ui_acceptance_v1.json}"

mkdir -p "$ART"
echo "=== Open-FDD product browser Soft-OPEN (Selenium) ==="
echo "artifact=$ART"

if [[ "${OPENFDD_UI_SELF_CHECK:-0}" == "1" ]]; then
  python3 "$PY" --self-check --artifact-dir "$ART" | tee "$ART/self_check.json"
  exit 0
fi

: "${OPENFDD_UI_BASE:?OPENFDD_UI_BASE required}"
: "${OPENFDD_EXPECTED_REVISION:?OPENFDD_EXPECTED_REVISION required (VERSION_MISMATCH gate)}"

EXTRA=()
if [[ "${OPENFDD_UI_HEADED:-0}" == "1" ]]; then
  EXTRA+=(--headed)
fi
if [[ "${OPENFDD_UI_REQUIRE_ALL:-1}" == "1" ]]; then
  EXTRA+=(--require-all)
fi

set +e
python3 "$PY" \
  --base-url "$OPENFDD_UI_BASE" \
  --expected-revision "$OPENFDD_EXPECTED_REVISION" \
  --manifest "$MANIFEST" \
  --artifact-dir "$ART" \
  "${EXTRA[@]}" | tee "$ART/runner.json"
RC=${PIPESTATUS[0]}
set -e

if [[ ! -f "$ART/SUMMARY.json" ]]; then
  echo "FAIL: missing SUMMARY.json (curl-only PASS banned)" >&2
  exit 2
fi

VERDICT="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["verdict"])' "$ART/SUMMARY.json")"
echo "verdict=$VERDICT rc=$RC"
# Never rewrite BLOCKED/FAIL into PASS.
case "$VERDICT" in
  PASS) exit 0 ;;
  PARTIAL) exit 4 ;;
  BLOCKED) exit 3 ;;
  *) exit 2 ;;
esac
