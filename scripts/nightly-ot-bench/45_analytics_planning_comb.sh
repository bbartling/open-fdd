#!/usr/bin/env bash
# Gate 45 — analytics planning comb (avg Utf8View / planning errors).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/scripts/nightly-ot-bench/lib.sh"
load_bench_env
BUILDING="${OPENFDD_GATE45_BUILDING:-${OPENFDD_SYNTH59_BUILDING:-OPENFDD_SYNTHETIC_59_RULE_WEEK_V1}}"
BASE="${OPENFDD_API_BASE:-${CENTRAL_BASE:-http://127.0.0.1:8080}}"
ART="${ARTIFACT_DIR:-$ROOT/reports/gate45_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$ART"
export OPENFDD_UI_GATE_SKIP_PLAYWRIGHT=1
OPENFDD_BUILDING_ID="$BUILDING" OPENFDD_API_BASE="$BASE" ARTIFACT_DIR="$ART" \
  bash "$ROOT/scripts/gates/ui_fdd_rcx_validate.sh"
echo "PASS gate 45 building=$BUILDING" | tee "$ART/gate45.txt"
