#!/usr/bin/env bash
# Run the #1483 in-process parallel ingest interaction tests with exact libtest names.
# Cargo treats each filter as a substring OR; a single quoted "a|b|c" is one literal
# substring and may match zero tests while still exiting 0.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

ROUNDS="${INGEST_PARALLEL_ROUNDS:-5}"
PACKAGE="${INGEST_PARALLEL_PACKAGE:-openfdd-central}"

TEST_NAMES=(
  ingest_idempotency_backfill_and_metrics_are_tenant_scoped
  t1406_model_point_engineer_overlay_controls
  t1423_4_cancel_route_is_operator_scoped_and_idempotent
)
EXPECTED_COUNT="${#TEST_NAMES[@]}"

names_csv="${TEST_NAMES[*]}"
echo "INGEST_PARALLEL_RECEIPT phase=start selected_names=${names_csv} expected_count=${EXPECTED_COUNT} rounds=${ROUNDS}"

for round in $(seq 1 "$ROUNDS"); do
  echo "=== ingest parallel interaction round ${round}/${ROUNDS} ==="
  log="$(mktemp)"
  cargo test -p "$PACKAGE" "${TEST_NAMES[@]}" -- --test-threads=8 2>&1 | tee "$log"
  running_line="$(grep -E '^running [0-9]+ tests' "$log" | tail -1 || true)"
  if [[ -z "$running_line" ]]; then
    echo "INGEST_PARALLEL_RECEIPT round=${round} running_count=0 selected_names=${names_csv} expected_count=${EXPECTED_COUNT} verdict=FAIL reason=no_running_line"
    rm -f "$log"
    exit 1
  fi
  running_count="$(sed -E 's/^running ([0-9]+) tests.*/\1/' <<<"$running_line")"
  echo "INGEST_PARALLEL_RECEIPT round=${round} running_count=${running_count} selected_names=${names_csv} expected_count=${EXPECTED_COUNT}"
  if [[ "$running_count" -eq 0 ]] || [[ "$running_count" -ne "$EXPECTED_COUNT" ]]; then
    echo "INGEST_PARALLEL_RECEIPT round=${round} verdict=FAIL reason=running_count_mismatch"
    rm -f "$log"
    exit 1
  fi
  rm -f "$log"
done

echo "INGEST_PARALLEL_RECEIPT phase=complete selected_names=${names_csv} expected_count=${EXPECTED_COUNT} rounds=${ROUNDS} verdict=PASS"
echo "ingest parallel interaction complete"
