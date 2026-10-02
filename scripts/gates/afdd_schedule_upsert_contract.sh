#!/usr/bin/env bash
# AFDD schedule + lookback-upsert contract (#1034, #1035).
#
# File checks always run. `--cargo` also runs the planner, merge, and
# DataFrame lookback tests. This does not claim field qualification.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

CARGO=0
if [[ "${1:-}" == "--cargo" ]]; then
  CARGO=1
fi

echo "== gate: afdd_schedule_upsert_contract =="

require() {
  local path="$1"
  local pattern="$2"
  if ! grep -qE "$pattern" "$path"; then
    echo "FAIL: $path missing /$pattern/" >&2
    exit 1
  fi
}

require crates/fdd_store/src/afdd_scheduler.rs "fn lookback_matches_cadence"
require crates/fdd_store/src/afdd_scheduler.rs "fn wall_clock_due"
require crates/fdd_store/src/afdd_scheduler.rs "wall_clock_downtime_is_one_lookback_window"
require crates/fdd_store/src/afdd_window.rs "fn merge_windowed_rule_result"
require crates/fdd_store/src/afdd_window.rs "fn rule_result_window_fingerprints"
require crates/fdd_store/src/afdd_window.rs '"update_all"'
require crates/fdd_rules/src/runner.rs "fn scope_table_to_time_window"
require services/central/src/afdd_scheduler.rs "result-slices"
require services/central/src/afdd_scheduler.rs "lookback_matches_cadence"
require scripts/nightly-ot-bench/38_acme_afdd_qualification.sh "outside_window"
require scripts/nightly-ot-bench/38_acme_afdd_qualification.sh "afdd_slice_identity"
python3 scripts/nightly-ot-bench/afdd_slice_identity.py
require scripts/nightly-ot-bench/38_acme_afdd_qualification.sh "update_all_rejected"
require scripts/nightly-ot-bench/38_acme_afdd_qualification.sh "central_stay_up"
require scripts/nightly-ot-bench/38_acme_afdd_qualification.sh "schedule_semantics"

if [[ "$CARGO" -eq 1 ]]; then
  if ! command -v cargo >/dev/null 2>&1; then
    echo "FAIL: cargo not found" >&2
    exit 1
  fi
  cargo test -p fdd_store --lib afdd_ -- --test-threads=8
  cargo test -p fdd_rules --lib time_window_prunes -- --test-threads=8
  cargo test -p fdd_rules --lib missing_file_starts_a_window -- --test-threads=8
fi

echo "PASS: afdd_schedule_upsert_contract"
