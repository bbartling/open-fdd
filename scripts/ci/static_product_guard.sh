#!/usr/bin/env bash
# Product UI guards: static /app/ assets on central + archived React rollback tree.
# Replaces React-only CI checks for Wave E+ (openfdd-web container retires in Wave F).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

STATIC="$ROOT/services/central/static/product"

echo "== static product asset guards =="

test -f "$STATIC/index.html"
test -f "$STATIC/assets/js/app.js"
test -f "$STATIC/assets/js/operations-tab.js"
test -f "$STATIC/assets/vendor/echarts.esm.min.js"
test -f "$STATIC/assets/vendor/LICENSE.echarts.txt"
test -f "$STATIC/assets/vendor/echarts.esm.min.js.version"

! grep -q 'unsafe-inline' "$STATIC/index.html"
! grep -q 'https://' "$STATIC/index.html"

echo "OK static product tree"

echo "== archived React rollback (Wave F retires container, not source) =="
test -f archive/product-ui/react-spa-v4/package.json
test -f archive/product-ui/react-spa-v4/Dockerfile
test -f docker/compose.react.yml

echo "== retired product UI paths stay absent =="
! test -d services/ui
! grep -qE 'openfdd-ui|services/ui|:8501' docker/compose.portal.yml docker/compose.central.yml docker/compose.csv.yml
! test -f workspace/dashboard/package.json
! test -d workspace/dashboard/src

echo "== central image: Rust-only runtime (no Node/Python in final stage) =="
grep -q 'debian:bookworm-slim' services/central/Dockerfile
grep -q 'openfdd-central' services/central/Dockerfile
! grep -qE 'node:|npm |python3' services/central/Dockerfile

echo "PASS static_product_guard.sh"
