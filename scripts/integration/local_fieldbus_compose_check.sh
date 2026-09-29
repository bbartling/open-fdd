#!/usr/bin/env bash
set -euo pipefail

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
OPENFDD_JWT_SECRET="compose-check-secret" docker compose -f docker/compose.local-fieldbus.yml config --format json >"$tmp"
jq -e '
  (.services.mqtt | not) and
  .services.central.environment.OPENFDD_MQTT_ENABLED == "0" and
  .services.fieldbus.environment.OPENFDD_MQTT_ENABLED == "0" and
  .services.fieldbus.environment.OPENFDD_INGEST_MODE == "local_fieldbus" and
  (.services.central.environment.OPENFDD_LOCAL_INGEST_TOKEN != null) and
  (.services.fieldbus.environment.OPENFDD_LOCAL_INGEST_TOKEN != null) and
  (.services.fieldbus.depends_on.central != null)
' "$tmp" >/dev/null
if jq -e '.. | strings | select(test("/mqtt|MQTT_(CA|CERT|KEY)"))' "$tmp" >/dev/null; then
  echo "FAIL: broker/certificate dependency in broker-free compose" >&2
  exit 1
fi
echo "PASS: compose.local-fieldbus.yml is broker-free and forwards local identity"
