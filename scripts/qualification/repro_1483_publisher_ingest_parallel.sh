#!/usr/bin/env bash
# Evidence helper for PR #1483 publisher ingest parallel flakes.
#
# Before fix (example parent dd4f6d9c): parallel openfdd-central tests on one Postgres
# could fail with plan_not_committed vs idempotency_conflict, overlay 403 vs 400, or
# T1423 cancel cancelled=0 when env mutated across threads without one process lock.
#
# After fix: UUID-scoped fixtures, run_env_locked / lock_env for OPENFDD_* mutators,
# postgres precedence when OPENFDD_DATABASE_URL is set (see INGEST_QUEUE.md).
#
# Usage (requires local Postgres at OPENFDD_TEST_DATABASE_URL):
#   ./scripts/qualification/repro_1483_publisher_ingest_parallel.sh before dd4f6d9c
#   ./scripts/qualification/repro_1483_publisher_ingest_parallel.sh after HEAD
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

PHASE="${1:-after}"
REF="${2:-HEAD}"

export OPENFDD_TEST_DATABASE_URL="${OPENFDD_TEST_DATABASE_URL:-postgresql://openfdd:openfdd@127.0.0.1:5432/openfdd}"
export OPENFDD_INGEST_SCOPE_DATABASE_REQUIRED=1

echo "repro_1483 phase=${PHASE} ref=${REF} database_required=1"

git fetch origin "$REF" 2>/dev/null || true
WORKTREE="$(mktemp -d)"
trap 'rm -rf "$WORKTREE"' EXIT

git worktree add -f "$WORKTREE" "$REF" >/dev/null
cd "$WORKTREE"

echo "=== isolated scope test (single thread) ==="
cargo test -p openfdd-central ingest_idempotency_backfill_and_metrics_are_tenant_scoped -- --nocapture --test-threads=1 \
  2>&1 | tee /tmp/repro_1483_scope.log
grep -q 'SCOPE_TEST_RECEIPT phase=postgres' /tmp/repro_1483_scope.log

echo "=== parallel interaction (same process, libtest threads=8) ==="
for round in $(seq 1 5); do
  echo "--- round ${round}/5 ---"
  cargo test -p openfdd-central \
    'ingest_idempotency_backfill_and_metrics_are_tenant_scoped|t1406_model_point_engineer_overlay_controls|t1423_4_cancel_route_is_operator_scoped_and_idempotent' \
    -- --test-threads=8
done

echo "repro_1483 phase=${PHASE} ref=${REF} ok"
