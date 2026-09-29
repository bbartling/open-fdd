#!/usr/bin/env bash
# Local/dual fieldbus acceptance proof. This uses only the public envelope
# contract and read-only health/stats endpoints; it never performs BACnet
# writes and does not require a private device inventory.
set -euo pipefail

FIELD_BASE="${OPENFDD_FIELDBUS_BASE:-http://127.0.0.1:8081}"
CENTRAL_BASE="${OPENFDD_LOCAL_CENTRAL_URL:-http://127.0.0.1:8080}"
TOKEN="${OPENFDD_LOCAL_INGEST_TOKEN:-}"
MODE="${OPENFDD_INGEST_MODE:-local_fieldbus}"

case "$MODE" in
  local_fieldbus|dual) ;;
  *) echo "FAIL: OPENFDD_INGEST_MODE must be local_fieldbus or dual (got $MODE)" >&2; exit 2 ;;
esac
[[ -n "$TOKEN" ]] || { echo "FAIL: OPENFDD_LOCAL_INGEST_TOKEN is required" >&2; exit 2; }

curl -fsS "$FIELD_BASE/api/health" >/dev/null
curl -fsS "$CENTRAL_BASE/api/health" >/dev/null

SITE="${OPENFDD_SITE_ID:-local}"
BUILDING="${OPENFDD_BUILDING_ID:-$SITE}"
EDGE="${OPENFDD_EDGE_ID:-fieldbus-1}"
MESSAGE_ID="$(cat /proc/sys/kernel/random/uuid)"
OBSERVED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
PAYLOAD="$(jq -cn \
  --arg schema "openfdd.mqtt.telemetry.v1" \
  --arg message_id "$MESSAGE_ID" \
  --arg observed_at "$OBSERVED_AT" \
  --arg site "$SITE" \
  --arg edge "$EDGE" \
  --arg building "$BUILDING" \
  '{schema:$schema,message_id:$message_id,sequence:1,observed_at:$observed_at,site_id:$site,edge_id:$edge,protocol:"bacnet",points:[{id:"acceptance:outside-air-temperature",display_name:"outside-air-temperature",kind:"number",value:70.0,quality:"good",tags:{building_id:$building,equipment_id:"acceptance-equipment",role:"oat"}}]}')"

headers=(
  -H "Authorization: Bearer $TOKEN"
  -H "Content-Type: application/json"
  -H "X-OpenFDD-Message-ID: $MESSAGE_ID"
  -H "X-OpenFDD-Sequence: 1"
  -H "X-OpenFDD-Building-ID: $BUILDING"
)
if [[ -n "${OPENFDD_TENANT_ID:-}" ]]; then
  headers+=( -H "X-OpenFDD-Tenant-ID: ${OPENFDD_TENANT_ID}" )
fi

response="$(curl -fsS "${CENTRAL_BASE%/}/api/ingest/local" "${headers[@]}" --data "$PAYLOAD")"
echo "$response" | jq -e '.ok == true and .duplicate == false' >/dev/null

# Replaying the exact envelope must be idempotent and must not create a second
# canonical row. This also exercises the dual local/cloud delivery guard.
replay="$(curl -fsS "${CENTRAL_BASE%/}/api/ingest/local" "${headers[@]}" --data "$PAYLOAD")"
echo "$replay" | jq -e '.ok == true and .duplicate == true' >/dev/null

echo "PASS: $MODE local fieldbus envelope accepted, persisted, and replay-deduplicated"
