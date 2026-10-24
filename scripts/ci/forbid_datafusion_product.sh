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

# A non-zero cargo tree exit, an error line, or an empty package list is a
# failed inspection. Swallowing stderr or forcing success hid a broken tree.
tree_err="$(mktemp)"
trap 'rm -f "$tree_err"' EXIT
tree_status=0
tree_out="$(cargo tree -p openfdd-central -e normal --prefix none 2>"$tree_err")" || tree_status=$?
if [[ "$tree_status" -ne 0 ]]; then
  echo "FAIL: cargo tree -p openfdd-central exited ${tree_status}"
  cat "$tree_err"
  fail=1
elif grep -E -q '^error(\[[^]]+\])?:' "$tree_err" || grep -E -q '^error(\[[^]]+\])?:' <<<"$tree_out"; then
  echo "FAIL: cargo tree -p openfdd-central reported an error"
  cat "$tree_err"
  printf '%s\n' "$tree_out"
  fail=1
elif [[ -z "${tree_out//[$' \t\r\n']/}" ]]; then
  echo "FAIL: cargo tree -p openfdd-central produced no package list"
  cat "$tree_err"
  fail=1
elif grep -E -q '^datafusion |^fdd_sql ' <<<"$tree_out"; then
  echo "FAIL: openfdd-central default tree includes datafusion or fdd_sql"
  grep -E 'datafusion|fdd_sql' <<<"$tree_out" || true
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
