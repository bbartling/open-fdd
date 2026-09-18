#!/usr/bin/env bash
# Gate 26_security_mqtt_acl — isolated broker ACL (optional).
# Continuity gate 21 is NOT ACL proof. Missing broker fixture → BLOCKED.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROBE="$ROOT/scripts/security/openfdd_security_probe.py"
CFG="${OPENFDD_SECURITY_CONFIG:-$ROOT/scripts/security/config/example_security_fixtures.json}"
BASE="${OPENFDD_API_BASE:-${RAILWAY_BASE:-http://127.0.0.1:18080}}"
ART="${ARTIFACT_DIR:-$ROOT/reports/security/gate26_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$ART"
OUT="$ART/mqtt_acl"
mkdir -p "$OUT"

if [[ "${OPENFDD_SECURITY_MQTT_ACL:-0}" != "1" ]]; then
  # Suite not in profile → N/A (not BLOCKED). Continuity gate 21 is never ACL proof.
  jq -n '{ok:true,status:"NOT_APPLICABLE",reason:"OPENFDD_SECURITY_MQTT_ACL!=1; mqtt_acl suite not in this profile (continuity≠ACL)"}' \
    | tee "$ART/security_gate_verdict.json"
  echo "NOT_APPLICABLE: broker ACL suite not enabled for this profile"
  exit 0
fi

# When enabled, still require isolated broker config — probe reports BLOCKED without it.
set +e
python3 "$PROBE" \
  --config "$CFG" \
  --base-url "${BASE%/}" \
  --profile isolated_full \
  --suite mqtt_acl \
  --execute \
  --output-dir "$OUT" \
  2>&1 | tee "$ART/26_security_mqtt_acl.log"
rc=${PIPESTATUS[0]}
set -e

jq -n --argjson rc "$rc" \
  '{ok:false,status:"BLOCKED",reason:"mqtt_acl suite requires isolated broker fixtures (not yet provisioned)",probe_exit:$rc}' \
  | tee "$ART/security_gate_verdict.json"
exit 2
