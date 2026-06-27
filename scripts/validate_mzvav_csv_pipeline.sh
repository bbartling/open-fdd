#!/usr/bin/env bash
# Validate MZVAV CSV → Haystack model → FDD → purge (local dev / CI helper).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CSV="${OPENFDD_MZVAV_CSV:-/mnt/c/Users/ben/Downloads/MZVAV-2-1.csv}"
if [[ ! -f "$CSV" ]]; then
  CSV="$ROOT/edge/tests/fixtures/mzvav-2-1-head.csv"
fi

echo "==> Rust unit + integration (csv_mzvav_integration)"
cd "$ROOT/edge"
OPENFDD_MZVAV_CSV="$CSV" cargo test --test csv_mzvav_integration

echo "==> Dashboard csvWorkbench tests"
cd "$ROOT/workspace/dashboard"
npm test -- --run

echo "==> OK — CSV pipeline validated against ${CSV}"
