#!/usr/bin/env bash
# Gate 26 skeleton — generated tenant MQTT ACL (Wave U U4).
# Until real broker fixture + positive observer land, this gate stays BLOCKED honesty.
set -euo pipefail
ART="${ARTIFACT_DIR:-$(pwd)/reports/security/gate26_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$ART"
if [[ "${OPENFDD_MQTT_ACL_EXECUTE:-0}" != "1" ]]; then
  jq -n '{
    ok:false,
    status:"BLOCKED",
    reason:"OPENFDD_MQTT_ACL_EXECUTE!=1; generated tenant ACL fixture not run",
    soft_open:"mqtt-key-mode-tenant-acl"
  }' | tee "$ART/mqtt_acl_verdict.json"
  exit 2
fi
# Placeholder for positive-observer ACL tests (see WAVE_U_MASTER U4).
jq -n '{
  ok:false,
  status:"BLOCKED",
  reason:"fixture not implemented — do not greenwash"
}' | tee "$ART/mqtt_acl_verdict.json"
exit 2
