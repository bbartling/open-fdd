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
if [[ "${OPENFDD_MQTT_ENABLED:-0}" =~ ^(1|true|yes|on)$ ]]; then
  echo "FAIL: broker-free local acceptance requires OPENFDD_MQTT_ENABLED=0" >&2
  exit 2
fi

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
  '{schema:$schema,message_id:$message_id,sequence:1,observed_at:$observed_at,site_id:$site,edge_id:$edge,protocol:"bacnet",points:[{id:"acceptance-point",display_name:"acceptance-point",kind:"number",value:70.0,quality:"good",tags:{building_id:$building,equipment_id:"acceptance-equipment",role:"sample"}}]}')"

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

unauth_status="$(curl -sS -o /dev/null -w '%{http_code}' "${CENTRAL_BASE%/}/api/ingest/local" \
  -H "Content-Type: application/json" --data "$PAYLOAD")"
[[ "$unauth_status" == "401" ]] || { echo "FAIL: unauthenticated local ingest returned $unauth_status" >&2; exit 1; }

post() {
  local body_file="$1"
  curl -sS -o "$body_file" -w '%{http_code}' "${CENTRAL_BASE%/}/api/ingest/local" \
    "${headers[@]}" --data "$PAYLOAD"
}

response_file="$(mktemp)"
replay_file=""
foreign_file=""
empty_file=""
trap 'rm -f "$response_file" "$replay_file" "$foreign_file" "$empty_file"' EXIT
status=""
for _ in $(seq 1 30); do
  status="$(post "$response_file")"
  if [[ "$status" == "200" ]] && jq -e '.ok == true and .duplicate == false and .pending == false and (.eligible_points > 0) and (.persisted_rows > 0)' "$response_file" >/dev/null; then
    break
  fi
  sleep 1
done
[[ "$status" == "200" ]] || { echo "FAIL: local ingest did not reach durable 200: HTTP $status $(cat "$response_file")" >&2; exit 1; }
jq -e '.ok == true and .duplicate == false and .pending == false and (.eligible_points > 0) and (.persisted_rows > 0)' "$response_file" >/dev/null || {
  echo "FAIL: zero eligible or persisted rows: $(cat "$response_file")" >&2; exit 1;
}

storage_root="${OPENFDD_ACCEPTANCE_STORAGE_ROOT:-${OPENFDD_STORAGE_ROOT:-workspace/openfdd}}"
row_files="$(find "$storage_root" -type f -name '*.parquet' -size +0c 2>/dev/null | wc -l | tr -d ' ')"
[[ "$row_files" -gt 0 ]] || { echo "FAIL: no non-empty Parquet storage found under $storage_root" >&2; exit 1; }

if [[ -n "${OPENFDD_ACCEPTANCE_RESTART_CMD:-}" ]]; then
  eval "$OPENFDD_ACCEPTANCE_RESTART_CMD"
fi

# Replaying the exact envelope must be idempotent and must not create a second
# canonical row. This also exercises the dual local/cloud delivery guard.
replay_file="$(mktemp)"
replay_status="$(curl -sS -o "$replay_file" -w '%{http_code}' "${CENTRAL_BASE%/}/api/ingest/local" "${headers[@]}" --data "$PAYLOAD")"
[[ "$replay_status" == "200" ]] || { echo "FAIL: replay returned HTTP $replay_status" >&2; exit 1; }
jq -e '.ok == true and .duplicate == true and .pending == false' "$replay_file" >/dev/null || {
  echo "FAIL: replay was not a committed duplicate: $(cat "$replay_file")" >&2; exit 1;
}

foreign_file="$(mktemp)"
foreign_payload="$(jq '.points[0].tags.building_id = "foreign-building"' <<<"$PAYLOAD")"
foreign_status="$(curl -sS -o "$foreign_file" -w '%{http_code}' "${CENTRAL_BASE%/}/api/ingest/local" \
  "${headers[@]}" --data "$foreign_payload")"
[[ "$foreign_status" == "403" ]] || { echo "FAIL: foreign building accepted with HTTP $foreign_status" >&2; exit 1; }

empty_file="$(mktemp)"
EMPTY_MESSAGE_ID="$(cat /proc/sys/kernel/random/uuid)"
empty_payload="$(jq --arg id "$EMPTY_MESSAGE_ID" '.message_id = $id | .points[0].tags = {}' <<<"$PAYLOAD")"
empty_headers=(
  -H "Authorization: Bearer $TOKEN"
  -H "Content-Type: application/json"
  -H "X-OpenFDD-Message-ID: $EMPTY_MESSAGE_ID"
  -H "X-OpenFDD-Sequence: 2"
  -H "X-OpenFDD-Building-ID: $BUILDING"
)
if [[ -n "${OPENFDD_TENANT_ID:-}" ]]; then
  empty_headers+=( -H "X-OpenFDD-Tenant-ID: ${OPENFDD_TENANT_ID}" )
fi
empty_status="$(curl -sS -o "$empty_file" -w '%{http_code}' "${CENTRAL_BASE%/}/api/ingest/local" \
  "${empty_headers[@]}" --data "$empty_payload")"
if [[ "$empty_status" == "200" ]] && jq -e '.pending == false and (.eligible_points // 0) == 0' "$empty_file" >/dev/null; then
  echo "FAIL: zero eligible points reached durable success" >&2
  exit 1
fi

echo "PASS: $MODE local fieldbus envelope authenticated, persisted, storage-verified, broker-free, foreign-building-denied, and replay-deduplicated"
