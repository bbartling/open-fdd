#!/usr/bin/env bash
# Synthetic-59 health-matrix fault-hour parity (Overview API vs expected_faults.csv).
# Requires OPENFDD_SYNTHETIC_59_RULE_WEEK_V1 loaded + FDD run (see synthetic_59_target_pair_soak.py).
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib.sh"
load_bench_env
cd "$ROOT"

ART="${ARTIFACT_DIR:-$(artifact_dir)}"
mkdir -p "$ART"

hdr "Synthetic-59 health matrix fault_h soak"
BUILDING="${SYNTH59_BUILDING_ID:-OPENFDD_SYNTHETIC_59_RULE_WEEK_V1}"

if [[ "${SKIP_SYNTH59_HEALTH_MATRIX:-0}" == "1" ]]; then
  skip "SKIP_SYNTH59_HEALTH_MATRIX=1"
  summary
  exit 0
fi

export OPENFDD_API_BASE="${OPENFDD_API_BASE:-$CENTRAL_BASE}"
LOG="$ART/synthetic_59_health_matrix_fault_hours_soak.log"
set +e
python3 "$ROOT/scripts/synthetic_59_health_matrix_fault_hours_soak.py" \
  --base "$OPENFDD_API_BASE" \
  --building-id "$BUILDING" 2>&1 | tee "$LOG"
RC=${PIPESTATUS[0]}
set -e

if [[ "$RC" -eq 0 ]]; then
  ok "health matrix fault_h parity ($BUILDING)"
else
  bad "health matrix fault_h soak failed (see synthetic_59_health_matrix_fault_hours_soak.log)"
fi

summary
exit "$RC"
