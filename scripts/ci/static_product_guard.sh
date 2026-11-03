#!/usr/bin/env bash
# Product UI guards: static /app/ assets on central + archived React rollback tree.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

STATIC="$ROOT/services/central/static/product"
PORTAL="$ROOT/docker/compose.portal.yml"

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

echo "== default portal recipe: central static UI, no openfdd-web =="
grep -q 'OPENFDD_STATIC_PRODUCT_UI' "$PORTAL"
! grep -qE '^[[:space:]]*web:' "$PORTAL"
! grep -q 'openfdd-web' "$PORTAL"

echo "== archived React rollback (compose.react.yml + GHCR openfdd-web) =="
test -f archive/product-ui/react-spa-v4/package.json
test -f archive/product-ui/react-spa-v4/Dockerfile
test -f docker/compose.react.yml
grep -q '3000:8080' docker/compose.react.yml

echo "== retired product UI paths stay absent =="
! test -d services/ui
! grep -qE 'openfdd-ui|services/ui|:8501' docker/compose.portal.yml docker/compose.central.yml docker/compose.csv.yml
! test -f workspace/dashboard/package.json
! test -d workspace/dashboard/src

echo "== central image: Rust-only runtime (no Node/Python in final stage) =="
grep -q 'debian:bookworm-slim' services/central/Dockerfile
grep -q 'openfdd-central' services/central/Dockerfile
! grep -qE 'node:|npm |python3' services/central/Dockerfile

bash -n scripts/ci/forbid_port_3000_product_docs.sh
./scripts/ci/forbid_port_3000_product_docs.sh

echo "== csv recipe: central-only static UI =="
! grep -qE '^[[:space:]]*web:' docker/compose.csv.yml
grep -q 'OPENFDD_STATIC_PRODUCT_UI' docker/compose.csv.yml

echo "PASS static_product_guard.sh"
