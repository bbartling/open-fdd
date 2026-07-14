#!/usr/bin/env bash
# Central service compiles and exposes /openapi.json in source routes.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

echo "== gate: openapi_central_present =="

if ! command -v cargo >/dev/null 2>&1; then
  echo "FAIL: cargo not found" >&2
  exit 1
fi

cargo check -p openfdd-central

if ! rg -n '"/openapi\.json"|/openapi\.json' services/central/src >/dev/null; then
  echo "FAIL: /openapi.json route not found under services/central/src" >&2
  exit 1
fi

echo "PASS: openapi_central_present"
