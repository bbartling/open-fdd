#!/usr/bin/env bash
# MQTTS gap blame — EDGE vs TRANSIT vs RAILWAY vs SPARSE_OK vs INCONCLUSIVE.
# Standalone from the OptiPlex (or any host that can reach Railway + the field edge):
#
#   export OPENFDD_API_BASE=https://<railway-web-or-central>
#   export OPENFDD_ADMIN_PASSWORD=...          # not printed
#   export OPENFDD_EDGE_BASE=http://127.0.0.1:8081
#   export OPENFDD_FIELDBUS_API_KEY=...        # if the edge bind is not open
#   export OPENFDD_GAP_BUILDING=ACME           # lab fixture; data-model types select equipment
#   export EXPECTED_EDGE_ID=vim-1
#   # window: OPENFDD_DIGEST_REPORT_HOURS or OPENFDD_GAP_WINDOW_HOURS (default 24)
#   ./scripts/nightly-ot-bench/39_mqtts_gap_blame.sh
#
# Exit 0: no proven loss and the window probes are complete.
# Exit 1: at least one EDGE / TRANSIT / RAILWAY row (scorecard has the class).
# Exit 2: INCONCLUSIVE only, or the window is missing a probe (not a clean pass).
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$DIR/../.." && pwd)"
ART="${ARTIFACT_DIR:-$ROOT/reports/mqtts_gap_blame_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$ART"
export OPENFDD_GAP_JSON="${OPENFDD_GAP_JSON:-$ART/mqtts_gap_blame.json}"
python3 "$DIR/mqtts_gap_blame.py" "$@"
