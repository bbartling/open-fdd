#!/usr/bin/env bash
# Gate 25b_security_post_stress — re-validate credentials + bounded authz reads.
# Finalize even after preceding failures; cannot erase precheck failure.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# Tip sequential / Railway: ACME ops env names ↔ A_OPS fixture names (Q4 / #999).
if [[ -z "${OPENFDD_USER_A_OPS_PASSWORD:-}" && -n "${OPENFDD_USER_ACME_OPS_PASSWORD:-}" ]]; then
  export OPENFDD_USER_A_OPS_PASSWORD="$OPENFDD_USER_ACME_OPS_PASSWORD"
fi
if [[ -z "${OPENFDD_USER_ACME_OPS_PASSWORD:-}" && -n "${OPENFDD_USER_A_OPS_PASSWORD:-}" ]]; then
  export OPENFDD_USER_ACME_OPS_PASSWORD="$OPENFDD_USER_A_OPS_PASSWORD"
fi
export OPENFDD_USER_A_OPS_USER="${OPENFDD_USER_A_OPS_USER:-${OPENFDD_USER_ACME_OPS_USER:-acme-ops}}"
export OPENFDD_OPS_A_PASSWORD="${OPENFDD_OPS_A_PASSWORD:-${OPENFDD_USER_A_OPS_PASSWORD:-}}"
export OPENFDD_OPS_A_USER="${OPENFDD_OPS_A_USER:-${OPENFDD_USER_A_OPS_USER:-acme-ops}}"
PROBE="$ROOT/scripts/security/openfdd_security_probe.py"
CFG_DEFAULT="$ROOT/scripts/security/config/example_security_fixtures.json"
if [[ -n "${RAILWAY_BASE:-}" \
   || "${OPENFDD_API_BASE:-}" == *railway.app* \
   || "${CENTRAL_BASE:-}" == *railway.app* \
   || "${OPENFDD_SECURITY_FIXTURES_PROFILE:-}" == "railway_hub" ]]; then
  CFG_DEFAULT="$ROOT/scripts/security/config/railway_hub_security_fixtures.json"
fi
CFG="${OPENFDD_SECURITY_CONFIG:-$CFG_DEFAULT}"
PROFILE="${OPENFDD_SECURITY_PROFILE:-live_readonly}"
BASE="${OPENFDD_API_BASE:-${RAILWAY_BASE:-${CENTRAL_BASE:-}}}"
ART="${ARTIFACT_DIR:-$ROOT/reports/security/gate25b_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$ART"
chmod 700 "$ART" 2>/dev/null || true
OUT="$ART/python_harness_post"
mkdir -p "$OUT"
echo "gate25b security fixtures: $CFG" | tee "$ART/fixtures_path.txt"

if [[ -z "$BASE" ]]; then
  jq -n '{ok:false,status:"BLOCKED",reason:"missing base URL"}' | tee "$ART/security_gate_verdict.json"
  exit 2
fi

if [[ "${OPENFDD_SECURITY_EXECUTE:-0}" != "1" ]]; then
  jq -n '{ok:false,status:"BLOCKED",reason:"OPENFDD_SECURITY_EXECUTE!=1; postcheck not run"}' \
    | tee "$ART/security_gate_verdict.json"
  exit 2
fi

PROBE_MARK="$OUT/.probe_started"
: > "$PROBE_MARK"
set +e
python3 "$PROBE" \
  --config "$CFG" \
  --base-url "${BASE%/}" \
  --profile "$PROFILE" \
  --suite X --suite Y \
  --execute \
  --timeout "${OPENFDD_SECURITY_TIMEOUT_S:-60}" \
  --max-requests "${OPENFDD_SECURITY_POST_MAX_REQUESTS:-100}" \
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

# Subset suites stay full_profile=false. Postcheck does not erase a precheck failure.
# ERROR checks stay ERROR. A stale PASS report cannot exit 0.
python3 - <<PY
import json, sys
from pathlib import Path
sys.path.insert(0, "$ROOT/scripts/security")
from openfdd_security.evidence import finalize_executed_gate
from openfdd_security.profiles import required_check_ids
report = Path("$REPORT")
child_rc = int("$rc")
req = required_check_ids("$PROFILE", ["X", "Y"])
started = Path("$PROBE_MARK").stat().st_mtime
verdict = finalize_executed_gate(
    report,
    expected_profile="$PROFILE",
    child_rc=child_rc,
    postcheck=True,
    require_full_profile=False,
    required_check_ids=req,
    probe_started_mtime=started,
)
verdict["note"] = "postcheck is suite subset; does not erase precheck failure"
verdict["report"] = str(report)
verdict["required_check_count"] = len(req)
Path("$ART/security_gate_verdict.json").write_text(json.dumps(verdict, indent=2) + "\n")
print(json.dumps(verdict))
status = verdict["status"]
sys.exit(0 if verdict["ok"] else (1 if status == "FAIL" else 2))
PY
