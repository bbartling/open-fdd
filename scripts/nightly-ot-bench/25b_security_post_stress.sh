#!/usr/bin/env bash
# Gate 25b_security_post_stress — re-validate credentials + bounded authz reads.
# Finalize even after preceding failures; cannot erase precheck failure.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROBE="$ROOT/scripts/security/openfdd_security_probe.py"
CFG="${OPENFDD_SECURITY_CONFIG:-$ROOT/scripts/security/config/example_security_fixtures.json}"
PROFILE="${OPENFDD_SECURITY_PROFILE:-live_readonly}"
BASE="${OPENFDD_API_BASE:-${RAILWAY_BASE:-${CENTRAL_BASE:-}}}"
ART="${ARTIFACT_DIR:-$ROOT/reports/security/gate25b_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$ART"
chmod 700 "$ART" 2>/dev/null || true
OUT="$ART/python_harness_post"
mkdir -p "$OUT"

if [[ -z "$BASE" ]]; then
  jq -n '{ok:false,status:"BLOCKED",reason:"missing base URL"}' | tee "$ART/security_gate_verdict.json"
  exit 2
fi

if [[ "${OPENFDD_SECURITY_EXECUTE:-0}" != "1" ]]; then
  jq -n '{ok:false,status:"BLOCKED",reason:"OPENFDD_SECURITY_EXECUTE!=1; postcheck not run"}' \
    | tee "$ART/security_gate_verdict.json"
  exit 2
fi

set +e
python3 "$PROBE" \
  --config "$CFG" \
  --base-url "${BASE%/}" \
  --profile "$PROFILE" \
  --suite X --suite Y \
  --execute \
  --max-requests "${OPENFDD_SECURITY_POST_MAX_REQUESTS:-60}" \
  --output-dir "$OUT" \
  2>&1 | tee "$ART/25b_security_post_stress.log"
rc=${PIPESTATUS[0]}
set -e

REPORT="$OUT/security_report.json"
if [[ ! -f "$REPORT" ]]; then
  jq -n '{ok:false,status:"ERROR",reason:"missing postcheck security_report.json"}' \
    | tee "$ART/security_gate_verdict.json"
  exit 2
fi

# Subset suites → full_profile=false → not fully_qualified; postcheck still must not FAIL.
# Reject empty checks, all-BLOCKED, and fabricated counts (E02/E03).
python3 - <<PY
import json, sys
from pathlib import Path
sys.path.insert(0, "$ROOT/scripts/security")
from openfdd_security.evidence import validate_report_for_qualification
report = Path("$REPORT")
ok, reason = validate_report_for_qualification(
    report,
    expected_profile="$PROFILE",
    require_full_profile=False,
    postcheck=True,
)
data = json.loads(report.read_text())
status = data.get("overall_status")
verdict = {
    "ok": ok,
    "status": "PASS" if ok else ("FAIL" if status == "FAIL" else "BLOCKED"),
    "reason": reason,
    "note": "postcheck is suite subset; does not erase precheck failure",
    "report": str(report),
}
Path("$ART/security_gate_verdict.json").write_text(json.dumps(verdict, indent=2) + "\n")
print(json.dumps(verdict))
sys.exit(0 if ok else (1 if status == "FAIL" else 2))
PY
