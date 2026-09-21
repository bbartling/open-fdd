#!/usr/bin/env bash
# Gate 26 — product openfdd-mqtt + provisioner ACL observer (Wave U V2 / UA-03).
# BLOCKED when OPENFDD_MQTT_ACL_EXECUTE!=1.
# Fixture eclipse-mosquitto only with OPENFDD_MQTT_ACL_ALLOW_FIXTURE_BROKER=1.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ART="${ARTIFACT_DIR:-$(pwd)/reports/security/gate26_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$ART"
# Accept short alias from operators / prior docs.
if [[ -z "${OPENFDD_MQTT_ACL_EXECUTE:-}" && "${MQTT_ACL_EXECUTE:-0}" == "1" ]]; then
  export OPENFDD_MQTT_ACL_EXECUTE=1
fi
if [[ "${OPENFDD_MQTT_ACL_EXECUTE:-0}" != "1" ]]; then
  jq -n '{
    ok:false,
    status:"BLOCKED",
    reason:"OPENFDD_MQTT_ACL_EXECUTE!=1; generated tenant ACL observer not run",
    soft_open:"mqtt-key-mode-tenant-acl",
    folded:["p2c-mqtt-acl-staging"]
  }' | tee "$ART/mqtt_acl_verdict.json" "$ART/security_gate_verdict.json"
  exit 2
fi

# Prefer tip pin for product broker image.
if [[ -z "${OPENFDD_MQTT_ACL_IMAGE:-}" && -n "${OPENFDD_IMAGE_TAG:-}" ]]; then
  export OPENFDD_MQTT_ACL_IMAGE="ghcr.io/bbartling/openfdd-mqtt:${OPENFDD_IMAGE_TAG}"
fi

OBS_OUT="$ART/observer"
mkdir -p "$OBS_OUT"
set +e
python3 -B "$ROOT/scripts/security/mqtt_tenant_acl_observer.py" \
  --out-dir "$OBS_OUT" \
  --require-live | tee "$ART/observer_stdout.json"
rc=${PIPESTATUS[0]}
set -e

if [[ -f "$OBS_OUT/mqtt_acl_observer.json" ]]; then
  cp "$OBS_OUT/mqtt_acl_observer.json" "$ART/mqtt_acl_verdict.json"
  # Permanent negative: EXECUTE path must not silently use fixture broker.
  if [[ "${OPENFDD_MQTT_ACL_ALLOW_FIXTURE_BROKER:-0}" != "1" ]]; then
    img=$(jq -r '.image // .checks[]?|select(.check=="mqtt.acl.live_broker_observer")|.image // empty' "$ART/mqtt_acl_verdict.json" 2>/dev/null | head -1)
    src=$(jq -r '.acl_source // empty' "$ART/mqtt_acl_verdict.json")
    if [[ "$src" == "fixture" ]] || [[ "$img" == eclipse-mosquitto* ]]; then
      jq -n --arg img "${img:-}" --arg src "${src:-}" '{
        ok:false,
        status:"FAIL",
        reason:"EXECUTE gate used fixture broker/ACL; set product openfdd-mqtt or OPENFDD_MQTT_ACL_ALLOW_FIXTURE_BROKER=1",
        soft_open:"mqtt-key-mode-tenant-acl",
        image:$img,
        acl_source:$src
      }' | tee "$ART/mqtt_acl_verdict.json" "$ART/security_gate_verdict.json"
      exit 1
    fi
  fi
  # run_security_gate records from security_gate_verdict.json (not mqtt_acl_verdict).
  jq '{
    ok: (.ok // (.status=="PASS")),
    status: (.status // (if .ok==true then "PASS" else "FAIL" end)),
    reason: (.reason // .detail // .live_broker // ""),
    image: (.image // null),
    acl_source: (.acl_source // null),
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
