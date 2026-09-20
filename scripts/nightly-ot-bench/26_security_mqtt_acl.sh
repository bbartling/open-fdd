#!/usr/bin/env bash
# Gate 26 — generated tenant MQTT ACL + positive observer (Wave U U4).
# BLOCKED honesty when OPENFDD_MQTT_ACL_EXECUTE!=1.
# When EXECUTE=1: runs scripts/security/mqtt_tenant_acl_observer.py (content +
# key-mode 640; live disposable mosquitto when Docker is available).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ART="${ARTIFACT_DIR:-$(pwd)/reports/security/gate26_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$ART"
if [[ "${OPENFDD_MQTT_ACL_EXECUTE:-0}" != "1" ]]; then
  jq -n '{
    ok:false,
    status:"BLOCKED",
    reason:"OPENFDD_MQTT_ACL_EXECUTE!=1; generated tenant ACL observer not run",
    soft_open:"mqtt-key-mode-tenant-acl",
    folded:["p2c-mqtt-acl-staging"]
  }' | tee "$ART/mqtt_acl_verdict.json"
  exit 2
fi

OBS_OUT="$ART/observer"
mkdir -p "$OBS_OUT"
set +e
python3 -B "$ROOT/scripts/security/mqtt_tenant_acl_observer.py" \
  --out-dir "$OBS_OUT" | tee "$ART/observer_stdout.json"
rc=${PIPESTATUS[0]}
set -e

if [[ -f "$OBS_OUT/mqtt_acl_observer.json" ]]; then
  cp "$OBS_OUT/mqtt_acl_observer.json" "$ART/mqtt_acl_verdict.json"
  # run_security_gate records from security_gate_verdict.json (not mqtt_acl_verdict).
  jq '{
    ok: (.ok // (.status=="PASS")),
    status: (.status // (if .ok==true then "PASS" else "FAIL" end)),
    reason: (.reason // .detail // .live_broker // ""),
    source: "mqtt_acl_observer.json"
  }' "$ART/mqtt_acl_verdict.json" | tee "$ART/security_gate_verdict.json" >/dev/null
else
  jq -n --argjson rc "$rc" '{
    ok:false,
    status:"FAIL",
    reason:"observer did not write mqtt_acl_observer.json",
    exit_code:$rc,
    soft_open:"mqtt-key-mode-tenant-acl"
  }' | tee "$ART/mqtt_acl_verdict.json" | tee "$ART/security_gate_verdict.json"
  exit 1
fi

# Also run unittest (content + key-mode) into artifacts.
set +e
python3 -B -m unittest tests.security.test_mqtt_tenant_acl -v \
  >"$ART/unittest_mqtt_tenant_acl.log" 2>&1
ut_rc=$?
set -e
echo "unittest_rc=$ut_rc" | tee -a "$ART/unittest_mqtt_tenant_acl.log"

if [[ "$ut_rc" -ne 0 ]]; then
  jq --argjson ut "$ut_rc" '.ok=false | .status="FAIL" | .unittest_rc=$ut' \
    "$ART/mqtt_acl_verdict.json" >"$ART/mqtt_acl_verdict.json.tmp"
  mv "$ART/mqtt_acl_verdict.json.tmp" "$ART/mqtt_acl_verdict.json"
  cp "$ART/mqtt_acl_verdict.json" "$ART/security_gate_verdict.json"
  exit 1
fi

if [[ "$rc" -eq 0 ]]; then
  # Refresh structured verdict after unittest PASS path.
  jq '{
    ok: (.ok // (.status=="PASS")),
    status: (.status // (if .ok==true then "PASS" else "FAIL" end)),
    reason: (.reason // .detail // .live_broker // "PASS"),
    source: "mqtt_acl_observer.json",
    unittest_rc: 0
  }' "$ART/mqtt_acl_verdict.json" >"$ART/security_gate_verdict.json"
  exit 0
fi
exit "$rc"
