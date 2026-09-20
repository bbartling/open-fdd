#!/usr/bin/env bash
# Gate 36_mv_sql_oracle_twin — Wave S4 Soft-OPEN SQL↔PyPI M&V twin.
# Default: BLOCKED (OPENFDD_SECURITY_EXECUTE!=1). FQ MEGA sets EXECUTE=1 + API base.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ART="${ARTIFACT_DIR:-$ROOT/reports/qualification/gate36_mv_twin_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$ART"
chmod 700 "$ART" 2>/dev/null || true

GATE_PY="$ROOT/scripts/qualification/mv_sql_oracle_twin_gate.py"
VERDICT="$ART/mv_sql_oracle_twin_verdict.json"

set +e
python3 "$GATE_PY" --artifact-dir "$ART" 2>&1 | tee "$ART/36_mv_sql_oracle_twin.log"
rc=${PIPESTATUS[0]}
set -e

if [[ ! -f "$VERDICT" ]]; then
  jq -n '{ok:false,status:"ERROR",reason:"missing mv_sql_oracle_twin_verdict.json"}' \
    | tee "$ART/mv_sql_oracle_twin_verdict.json"
  # Also mirror security-style name for stress recorders that look for *_verdict.json
  cp "$ART/mv_sql_oracle_twin_verdict.json" "$ART/security_gate_verdict.json" 2>/dev/null || true
  exit 1
fi

# Copy alias for operators grepping security_gate_verdict.json patterns
cp "$VERDICT" "$ART/security_gate_verdict.json" 2>/dev/null || true

status="$(jq -r '.status // "ERROR"' "$VERDICT")"
echo "gate36 status=$status rc=$rc artifact=$ART"
exit "$rc"
