#!/usr/bin/env bash
# Gate 43 — Overview browser analytics (Playwright optional; backend probe required).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec env OPENFDD_UI_GATE_SKIP_PLAYWRIGHT="${OPENFDD_UI_GATE_SKIP_PLAYWRIGHT:-0}" \
  bash "$ROOT/scripts/nightly-ot-bench/45_analytics_planning_comb.sh"
