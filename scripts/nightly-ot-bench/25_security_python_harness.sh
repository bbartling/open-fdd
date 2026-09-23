#!/usr/bin/env bash
# Gate 25_security_python_harness — pre-stress Python security probe.
# Distinct from 25_wave_l_tenant_ui_session.sh (Wave L OFF smoke).
# Default: dry-run plan when OPENFDD_SECURITY_EXECUTE!=1 (HOLD-safe).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROBE="$ROOT/scripts/security/openfdd_security_probe.py"
CFG="${OPENFDD_SECURITY_CONFIG:-$ROOT/scripts/security/config/example_security_fixtures.json}"
PROFILE="${OPENFDD_SECURITY_PROFILE:-live_readonly}"
BASE="${OPENFDD_API_BASE:-${RAILWAY_BASE:-${CENTRAL_BASE:-}}}"
ART="${ARTIFACT_DIR:-$ROOT/reports/security/gate25_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$ART"
chmod 700 "$ART" 2>/dev/null || true

if [[ -z "$BASE" ]]; then
  echo "BLOCKED: OPENFDD_API_BASE / RAILWAY_BASE / CENTRAL_BASE unset" | tee "$ART/blocked.txt"
  jq -n --arg r "missing base URL" '{ok:false,status:"BLOCKED",reason:$r}' \
    | tee "$ART/security_gate_verdict.json"
  exit 2
fi

# Unique per-gate artifact root (never share with gates 31/33).
OUT="$ART/python_harness"
mkdir -p "$OUT"

ARGS=(
  python3 "$PROBE"
  --config "$CFG"
  --base-url "${BASE%/}"
  --profile "$PROFILE"
  --output-dir "$OUT"
)

if [[ "${OPENFDD_SECURITY_EXECUTE:-0}" == "1" ]]; then
  ARGS+=(--execute)
  if [[ "$PROFILE" == "isolated_full" && "${OPENFDD_SECURITY_ALLOW_WRITES:-0}" == "1" ]]; then
    ARGS+=(--allow-fixture-writes)
  fi
  # Railway field / live hub: foreign analytics authz POSTs can exceed the default
  # 10s transport budget under concurrent stress (idle still returns 403 in ~300ms).
  if [[ "${RAILWAY_ONLY:-0}" == "1" || "$PROFILE" == "live_readonly" ]]; then
    ARGS+=(--timeout "${OPENFDD_SECURITY_TIMEOUT_S:-60}")
  fi
else
  ARGS+=(--dry-run)
fi

set +e
"${ARGS[@]}" 2>&1 | tee "$ART/25_security_python_harness.log"
rc=${PIPESTATUS[0]}
set -e

REPORT="$OUT/security_report.json"
if [[ ! -f "$REPORT" ]]; then
  echo "ERROR: missing $REPORT" | tee -a "$ART/25_security_python_harness.log"
  jq -n '{ok:false,status:"ERROR",reason:"missing security_report.json"}' \
    | tee "$ART/security_gate_verdict.json"
  exit 2
fi

# Dry-run cannot PASS qualification even if exit 0
if [[ "${OPENFDD_SECURITY_EXECUTE:-0}" != "1" ]]; then
  jq -n \
    --arg report "$REPORT" \
    '{ok:false,status:"BLOCKED",reason:"dry-run only (set OPENFDD_SECURITY_EXECUTE=1 for evidence)",report:$report}' \
    | tee "$ART/security_gate_verdict.json"
  echo "BLOCKED: dry-run plan written; not security qualification evidence"
  exit 2
fi

# Validate structured result (not exit-code alone)
python3 - <<PY
import json, sys
from pathlib import Path
sys.path.insert(0, "$ROOT/scripts/security")
from openfdd_security.evidence import validate_report_for_qualification
report = Path("$REPORT")
meta_path = report.parent / "security_report.sha256"
expected = None
if meta_path.is_file():
    expected = json.loads(meta_path.read_text()).get("sha256")
ok, reason = validate_report_for_qualification(
    report,
    expected_profile="$PROFILE",
    expected_sha256=expected,
)
verdict = {"ok": ok, "status": "PASS" if ok else "FAIL", "reason": reason, "report": str(report)}
Path("$ART/security_gate_verdict.json").write_text(json.dumps(verdict, indent=2) + "\n")
print(json.dumps(verdict))
sys.exit(0 if ok else 1)
PY
