#!/usr/bin/env bash
# Gate 43 — Overview browser analytics (Playwright required for browser qualify).
#
# Soft-OPEN 370 T3b / M70-10: do NOT delegate to gate45 with Playwright forced
# off. Backend planning stays gate45; skipped browser = BLOCKED for browser
# qualification (never PASS).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/scripts/nightly-ot-bench/lib.sh"
load_bench_env
BUILDING="${OPENFDD_GATE43_BUILDING:-${OPENFDD_SYNTH59_BUILDING:-OPENFDD_SYNTHETIC_59_RULE_WEEK_V1}}"
BASE="${OPENFDD_API_BASE:-${CENTRAL_BASE:-http://127.0.0.1:8080}}"
ART="${ARTIFACT_DIR:-$ROOT/reports/gate43_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$ART"

if [[ "${OPENFDD_UI_GATE_SKIP_PLAYWRIGHT:-0}" == "1" ]]; then
  echo "BLOCKED: Playwright skipped (OPENFDD_UI_GATE_SKIP_PLAYWRIGHT=1) — not a browser PASS" \
    | tee "$ART/BLOCKED.txt"
  exit 2
fi

# Backend planning comb first (gate45 forces Playwright off by design).
OPENFDD_BUILDING_ID="$BUILDING" OPENFDD_API_BASE="$BASE" ARTIFACT_DIR="$ART/backend" \
  bash "$ROOT/scripts/nightly-ot-bench/45_analytics_planning_comb.sh" \
  | tee "$ART/backend_comb.txt"

# Real browser path — ui_fdd_rcx_validate without skip override.
export OPENFDD_UI_GATE_SKIP_PLAYWRIGHT=0
OPENFDD_BUILDING_ID="$BUILDING" OPENFDD_API_BASE="$BASE" ARTIFACT_DIR="$ART/browser" \
  bash "$ROOT/scripts/gates/ui_fdd_rcx_validate.sh" \
  | tee "$ART/browser.txt"

echo "PASS gate 43 backend+browser building=$BUILDING" | tee "$ART/gate43.txt"
