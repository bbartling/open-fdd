#!/usr/bin/env bash
# Containerized BACpypes3 -> Open-FDD fieldbus -> MQTTS -> central ingest + historian smoke.
# Open-FDD product images are pulled from GHCR; only the tiny BACpypes3 simulator is built locally.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

TAG="${OPENFDD_IMAGE_TAG:?set OPENFDD_IMAGE_TAG to an immutable sha-<7> tag}"
if [[ ! "$TAG" =~ ^sha-[0-9a-f]{7}$ ]]; then
  echo "OPENFDD_IMAGE_TAG must match sha-<7 lowercase hex>, got: $TAG" >&2
  exit 1
fi

for cmd in docker openssl curl jq; do
  command -v "$cmd" >/dev/null || { echo "missing required command: $cmd" >&2; exit 1; }
done

docker info >/dev/null

TMP="$(mktemp -d)"
PROJECT="openfdd-bacnet-mqtt-ci-${RANDOM}-${RANDOM}"
COMPOSE=(docker compose -p "$PROJECT" -f docker/compose.bacnet-mqtt-ci.yml)
export OPENFDD_BACNET_MQTT_CERT_DIR="$TMP/mqtt"
export OPENFDD_JWT_SECRET="bacnet-mqtt-ci-jwt-${PROJECT}"
export OPENFDD_ADMIN_PASSWORD="bacnet-mqtt-ci-admin"

cleanup() {
  "${COMPOSE[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT

mkdir -p "$TMP/mqtt"/{broker,central,edge}
cat > "$TMP/mqtt/acl" <<'ACL'
user edge:ci:fieldbus-1
topic write openfdd/v1/sites/ci/edges/fieldbus-1/telemetry/#
topic write openfdd/v1/sites/ci/edges/fieldbus-1/metadata/#
topic write openfdd/v1/sites/ci/edges/fieldbus-1/discovery/#
topic write openfdd/v1/sites/ci/edges/fieldbus-1/status
topic write openfdd/v1/sites/ci/edges/fieldbus-1/acks/#
topic read openfdd/v1/sites/ci/edges/fieldbus-1/commands/#

user central:ci
topic write openfdd/v1/sites/ci/edges/+/commands/#
topic read openfdd/v1/sites/ci/#
ACL

# Ephemeral CA for this isolated integration network.
openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
  -subj '/CN=openfdd-bacnet-mqtt-ci-ca' \
  -keyout "$TMP/ca.key.pem" -out "$TMP/ca.pem" >/dev/null 2>&1

issue_cert() {
  local name="$1" cn="$2" usage="$3" san="${4:-}"
  local ext="$TMP/${name}.ext"
  {
    echo "extendedKeyUsage=${usage}"
    [[ -n "$san" ]] && echo "subjectAltName=${san}"
  } > "$ext"
  openssl req -newkey rsa:2048 -nodes -subj "/CN=${cn}" \
    -keyout "$TMP/${name}.key.pem" -out "$TMP/${name}.csr.pem" >/dev/null 2>&1
  openssl x509 -req -days 1 -sha256 \
    -in "$TMP/${name}.csr.pem" \
    -CA "$TMP/ca.pem" -CAkey "$TMP/ca.key.pem" -CAcreateserial \
    -extfile "$ext" -out "$TMP/${name}.cert.pem" >/dev/null 2>&1
}

issue_cert server mqtt serverAuth 'DNS:mqtt,IP:172.30.0.30'
# Match the production openfdd-provision certificate identity contract exactly.
issue_cert central 'central:ci' clientAuth
issue_cert edge 'edge:ci:fieldbus-1' clientAuth

cp "$TMP/ca.pem" "$TMP/mqtt/broker/ca.pem"
cp "$TMP/server.cert.pem" "$TMP/mqtt/broker/server.cert.pem"
cp "$TMP/server.key.pem" "$TMP/mqtt/broker/server.key.pem"

cp "$TMP/ca.pem" "$TMP/mqtt/central/ca.pem"
cp "$TMP/central.cert.pem" "$TMP/mqtt/central/central.cert.pem"
cp "$TMP/central.key.pem" "$TMP/mqtt/central/central.key.pem"

cp "$TMP/ca.pem" "$TMP/mqtt/edge/ca.pem"
cp "$TMP/edge.cert.pem" "$TMP/mqtt/edge/edge.cert.pem"
cp "$TMP/edge.key.pem" "$TMP/mqtt/edge/edge.key.pem"

# Product containers intentionally run non-root. These are one-run ephemeral CI credentials
# under a private mktemp directory; make mounted files readable by those container users.
chmod 755 "$TMP" "$TMP/mqtt" "$TMP/mqtt"/{broker,central,edge}
chmod 644 "$TMP/mqtt/acl" "$TMP/mqtt"/*/*.pem

echo "== Pull exact Open-FDD images: $TAG =="
for image in openfdd-mqtt openfdd-central openfdd-fieldbus; do
  docker pull "ghcr.io/bbartling/${image}:${TAG}"
done

echo "== Build only the lightweight BACpypes3 simulator =="
"${COMPOSE[@]}" build bacnet-sim

echo "== Start isolated BACnet/MQTTS integration stack =="
"${COMPOSE[@]}" up -d --no-build

wait_http() {
  local url="$1" label="$2" deadline=$((SECONDS + 120))
  until curl -fsS "$url" >/dev/null 2>&1; do
    if (( SECONDS >= deadline )); then
      echo "FAIL: timeout waiting for $label ($url)" >&2
      "${COMPOSE[@]}" ps >&2 || true
      "${COMPOSE[@]}" logs --tail=200 >&2 || true
      exit 1
    fi
    sleep 2
  done
  echo "OK $label"
}

wait_http http://127.0.0.1:18081/health "fieldbus health"
wait_http http://127.0.0.1:18080/api/health "central health"

# Exercise the real Open-FDD BACnet client against the BACpypes3 server.
echo "== BACnet read =="
READ_JSON='{"device_instance":3456,"object_type":"analog-value","object_instance":1,"property_id":"present-value"}'
READ_RESPONSE="$(curl -fsS -X POST http://127.0.0.1:18081/bacnet/read \
  -H 'Content-Type: application/json' -d "$READ_JSON")"
echo "$READ_RESPONSE" | jq -e '
  .ok == true and
  .device_instance == 3456 and
  .object_type == "analog-value" and
  .object_instance == 1 and
  (.value | type == "number")
' >/dev/null
echo "OK BACnet analog-value:1 present-value=$(echo "$READ_RESPONSE" | jq -r '.value')"

# Force a poll immediately and prove the configured BACnet rows reached poll state before MQTT.
POLL_RESPONSE="$(curl -fsS -X POST http://127.0.0.1:18081/bacnet/poll/once)"
echo "$POLL_RESPONSE" | jq -e '.ok == true and (.points_polled >= 1)' >/dev/null
POLL_STATUS="$(curl -fsS http://127.0.0.1:18081/bacnet/poll/status)"
echo "$POLL_STATUS" | jq -e '
  .ok == true and
  (.last_values | any(
    .device_instance == 3456 and
    .object_type == "analog-value" and
    .object_instance == 1 and
    .point_name == "discharge-air-temp"
  ))
' >/dev/null
echo "OK fieldbus poll state contains BACpypes3 point"

TOKEN="$(curl -fsS -X POST http://127.0.0.1:18080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"bacnet-mqtt-ci-admin"}' \
  | jq -r '.token // .access_token // empty')"
if [[ -z "$TOKEN" ]]; then
  echo "FAIL: central login did not return a token" >&2
  "${COMPOSE[@]}" logs --tail=200 central >&2 || true
  exit 1
fi

# Wait until central observes, parses, and accepts the fieldbus BACnet telemetry envelope.
deadline=$((SECONDS + 90))
while true; do
  MONITOR="$(curl -fsS http://127.0.0.1:18080/api/mqtt/monitor \
    -H "Authorization: Bearer $TOKEN")"
  EDGE="$(curl -fsS http://127.0.0.1:18080/api/edges/fieldbus-1 \
    -H "Authorization: Bearer $TOKEN")"
  STATS="$(curl -fsS http://127.0.0.1:18080/api/ingest/stats \
    -H "Authorization: Bearer $TOKEN")"

  monitor_ok=0
  edge_ok=0
  stats_ok=0
  echo "$MONITOR" | jq -e '
      .connected == true and
      (.received_messages >= 1) and
      (.recent_messages | any(
        .topic == "openfdd/v1/sites/ci/edges/fieldbus-1/telemetry/bacnet" and
        (.payload_preview | contains("bacnet:3456:analog-value:1")) and
        (.payload_preview | contains("BUILDING_CI"))
      ))
    ' >/dev/null && monitor_ok=1 || true
  echo "$EDGE" | jq -e '
      .ok == true and
      .edge_id == "fieldbus-1" and
      .last_telemetry != null and
      .last_telemetry.site_id == "ci" and
      .last_telemetry.edge_id == "fieldbus-1" and
      (.last_telemetry.points | any(
        .id == "bacnet:3456:analog-value:1" and
        .tags.building_id == "BUILDING_CI"
      ))
    ' >/dev/null && edge_ok=1 || true
  echo "$STATS" | jq -e '
      .ok == true and
      (.ingest_ok >= 1) and
      .ingest_reject == 0 and
      .dead_letters == 0
    ' >/dev/null && stats_ok=1 || true

  if (( monitor_ok == 1 && edge_ok == 1 && stats_ok == 1 )); then
    break
  fi
  if (( SECONDS >= deadline )); then
    echo "FAIL: central never completed expected parsed BACnet ingestion" >&2
    echo "--- poll status ---" >&2; echo "$POLL_STATUS" | jq . >&2 || true
    echo "--- fieldbus spool ---" >&2
    "${COMPOSE[@]}" exec -T fieldbus sh -c 'find /spool -maxdepth 2 -type f -print -exec cat {} \;' >&2 || true
    echo "--- monitor ---" >&2; echo "$MONITOR" | jq . >&2 || true
    echo "--- edge ---" >&2; echo "$EDGE" | jq . >&2 || true
    echo "--- ingest stats ---" >&2; echo "$STATS" | jq . >&2 || true
    "${COMPOSE[@]}" logs --tail=300 fieldbus central mqtt bacnet-sim >&2 || true
    exit 1
  fi
  sleep 3
done

echo "OK central parsed and accepted canonical BACnet telemetry over MQTTS"

# Durability proof: the live historian writes a canonical watermark only after persistence.
# Path is under OPENFDD_STORAGE_URL root (compose: file:///workspace/openfdd).
WATERMARK=/workspace/openfdd/state/live-historian/latest-telemetry.json
deadline=$((SECONDS + 45))
until "${COMPOSE[@]}" exec -T central sh -c "test -s '$WATERMARK'"; do
  if (( SECONDS >= deadline )); then
    echo "FAIL: canonical live historian watermark was not persisted" >&2
    "${COMPOSE[@]}" exec -T central sh -c 'find /workspace/openfdd /workspace/.cache/parquet -maxdepth 6 -type f -print 2>/dev/null | sort' >&2 || true
    "${COMPOSE[@]}" logs --tail=250 central >&2 || true
    exit 1
  fi
  sleep 2
done

echo "OK canonical live historian persisted telemetry watermark"
echo "$MONITOR" | jq '{connected, received_messages, errors, recent_messages: [.recent_messages[] | {topic, payload_bytes, payload_encoding}]}'
echo "$STATS" | jq '{ingest_ok, ingest_dup, ingest_reject, dead_letters}'
echo "PASS: BACpypes3 -> Open-FDD BACnet fieldbus -> MQTTS -> central ingest -> historian integration"
