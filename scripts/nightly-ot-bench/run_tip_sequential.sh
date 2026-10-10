#!/usr/bin/env bash
# Tip sequential prove wrapper (#999 / #1179 harness).
# Exports RAILWAY_ONLY + BASE/CENTRAL_BASE from OPENFDD_API_BASE so first
# attempts stop hitting 127.0.0.1.
#
# Usage:
#   OPENFDD_API_BASE=https://… ./scripts/nightly-ot-bench/run_tip_sequential.sh
#   OPENFDD_API_BASE=https://… ./scripts/nightly-ot-bench/run_tip_sequential.sh 19 25 25b 26 35 36 37 38 39
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/scripts/nightly-ot-bench/lib.sh"

export RAILWAY_ONLY=1
BASE_URL="${OPENFDD_API_BASE:-${RAILWAY_BASE:-${CENTRAL_BASE:-${BASE:-}}}}"
if [[ -z "$BASE_URL" ]]; then
  echo "FAIL: set OPENFDD_API_BASE (or RAILWAY_BASE)" >&2
  exit 2
fi
export OPENFDD_API_BASE="$BASE_URL"
export RAILWAY_BASE="$BASE_URL"
export CENTRAL_BASE="$BASE_URL"
export BASE="$BASE_URL"

GATES=("$@")
if [[ ${#GATES[@]} -eq 0 ]]; then
  GATES=(19 25 25b 26 35 36 37 38 39 43 44 45 46 47)
fi

ART="${ARTIFACT_DIR:-$ROOT/reports/tip_sequential_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$ART"
echo "tip sequential BASE=$BASE RAILWAY_ONLY=$RAILWAY_ONLY art=$ART" | tee "$ART/env.txt"

fail=0
for g in "${GATES[@]}"; do
  case "$g" in
    19) script="$ROOT/scripts/nightly-ot-bench/19_engineering_bundle_validate.sh" ;;
    25) script="$ROOT/scripts/nightly-ot-bench/25_security_python_harness.sh" ;;
    25b) script="$ROOT/scripts/nightly-ot-bench/25b_security_post_stress.sh" ;;
    26) script="$ROOT/scripts/nightly-ot-bench/26_security_mqtt_acl.sh" ;;
    35) script="$ROOT/scripts/nightly-ot-bench/35_mqtt_telemetry_pause_resume.sh" ;;
    36) script="$ROOT/scripts/nightly-ot-bench/36_model_ecm_qualification.sh" ;;
    37) script="$ROOT/scripts/nightly-ot-bench/37_acme_analytics_charts.sh" ;;
    38) script="$ROOT/scripts/nightly-ot-bench/38_acme_afdd_qualification.sh" ;;
    39) script="$ROOT/scripts/nightly-ot-bench/39_mqtts_gap_blame.sh" ;;
    40) script="$ROOT/scripts/nightly-ot-bench/40_no_id_heuristics.sh" ;;
    43) script="$ROOT/scripts/nightly-ot-bench/43_overview_browser_analytics.sh" ;;
    44) script="$ROOT/scripts/nightly-ot-bench/44_run_now_latency_budget.sh" ;;
    45) script="$ROOT/scripts/nightly-ot-bench/45_analytics_planning_comb.sh" ;;
    46) script="$ROOT/scripts/nightly-ot-bench/46_data_model_integrity.sh" ;;
    47) script="$ROOT/scripts/nightly-ot-bench/47_mid_request_memory_shed.sh" ;;
    *) echo "unknown gate $g" >&2; fail=1; continue ;;
  esac
  echo "=== gate $g ===" | tee -a "$ART/run.log"
  ARTIFACT_DIR="$ART/gate_$g" bash "$script" 2>&1 | tee -a "$ART/run.log" || {
    rc=${PIPESTATUS[0]:-1}
    echo "gate $g rc=$rc" | tee -a "$ART/run.log"
    fail=1
  }
done
exit "$fail"
