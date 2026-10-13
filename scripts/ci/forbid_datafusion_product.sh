#!/usr/bin/env bash
# Wave-X C2: product central must not depend on DataFusion / fdd_sql.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
fail=0

if [[ -f services/central/src/analytics/historian_datafusion.rs ]]; then
  echo "FAIL: historian_datafusion.rs still present"
  fail=1
fi

if rg -n '^legacy-datafusion|^legacy-parquet|legacy-datafusion\s*=' \
  services/central/Cargo.toml edge/Cargo.toml crates/fdd_rules/Cargo.toml 2>/dev/null | head -20 | grep -q .; then
  echo "FAIL: legacy-datafusion / legacy-parquet features still declared"
  rg -n 'legacy-datafusion|legacy-parquet' services/central/Cargo.toml edge/Cargo.toml crates/fdd_rules/Cargo.toml || true
  fail=1
fi

tree_out="$(cargo tree -p openfdd-central -e normal --prefix none 2>/dev/null || true)"
if echo "$tree_out" | rg -q '^datafusion |^fdd_sql '; then
  echo "FAIL: openfdd-central default tree includes datafusion or fdd_sql"
  echo "$tree_out" | rg 'datafusion|fdd_sql' || true
  fail=1
fi

if rg -n '"crates/fdd_cli"|"crates/fdd_bench"|"crates/fdd_sql"' Cargo.toml | head -5 | grep -q .; then
  echo "FAIL: workspace still lists fdd_sql / fdd_cli / fdd_bench"
  fail=1
fi

if [[ "$fail" -ne 0 ]]; then
  echo "forbid_datafusion_product: FAILED"
  exit 1
fi
echo "forbid_datafusion_product: OK"
