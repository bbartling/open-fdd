#!/usr/bin/env bash
# Gate 25_security_python_harness — pre-stress Python security probe.
# Distinct from 25_wave_l_tenant_ui_session.sh (Wave L OFF smoke).
# Default: dry-run plan when OPENFDD_SECURITY_EXECUTE!=1 (HOLD-safe).
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
# Live Railway hub stress must use hub tenants (acme / building_100), not example
# tenant_a/tenant_b — tip FINAL gate25 FAIL on sha-93f8ec2 (#999 / Soft-OPEN handoff).
if [[ -n "${RAILWAY_BASE:-}" \
   || "${OPENFDD_API_BASE:-}" == *railway.app* \
   || "${CENTRAL_BASE:-}" == *railway.app* \
   || "${OPENFDD_SECURITY_FIXTURES_PROFILE:-}" == "railway_hub" ]]; then
  CFG_DEFAULT="$ROOT/scripts/security/config/railway_hub_security_fixtures.json"
fi
CFG="${OPENFDD_SECURITY_CONFIG:-$CFG_DEFAULT}"
PROFILE="${OPENFDD_SECURITY_PROFILE:-live_readonly}"
BASE="${OPENFDD_API_BASE:-${RAILWAY_BASE:-${CENTRAL_BASE:-}}}"
ART="${ARTIFACT_DIR:-$ROOT/reports/security/gate25_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$ART"
chmod 700 "$ART" 2>/dev/null || true

echo "gate25 security fixtures: $CFG" | tee "$ART/fixtures_path.txt"

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

PROBE_MARK="$OUT/.probe_started"
: > "$PROBE_MARK"
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

# Recompute from checks[]. Stale PASS, ERROR checks, and child_rc contradictions
# cannot exit 0. BLOCKED is only for missing fixtures, not transport faults.
python3 - <<PY
import json, sys
from pathlib import Path
sys.path.insert(0, "$ROOT/scripts/security")
from openfdd_security.evidence import finalize_executed_gate
from openfdd_security.profiles import required_check_ids
report = Path("$REPORT")
meta_path = report.parent / "security_report.sha256"
expected = None
if meta_path.is_file():
    expected = json.loads(meta_path.read_text()).get("sha256")
child_rc = int("$rc")
req = required_check_ids("$PROFILE", ["X", "Y", "Z"])
started = Path("$PROBE_MARK").stat().st_mtime
verdict = finalize_executed_gate(
    report,
    expected_profile="$PROFILE",
    child_rc=child_rc,
    required_check_ids=req,
    expected_sha256=expected,
    probe_started_mtime=started,
)
verdict["report"] = str(report)
verdict["required_check_count"] = len(req)
Path("$ART/security_gate_verdict.json").write_text(json.dumps(verdict, indent=2) + "\n")
print(json.dumps(verdict))
status = verdict["status"]
sys.exit(0 if verdict["ok"] else (1 if status == "FAIL" else 2))
PY
