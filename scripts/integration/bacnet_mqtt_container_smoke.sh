#!/usr/bin/env bash
# Containerized BACpypes3 -> Open-FDD fieldbus -> MQTTS -> central monitor smoke.
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
  "${COMPOSE[@]}" down --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT

mkdir -p "$TMP/mqtt"/{broker,central,edge}
printf 'topic readwrite #\n' > "$TMP/mqtt/acl"

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
issue_cert central central clientAuth
issue_cert edge edge-ci-fieldbus-1 clientAuth

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

# Force a poll immediately; the MQTT bridge publishes poll snapshots on its interval.
curl -fsS -X POST http://127.0.0.1:18081/bacnet/poll/once | jq -e '.ok == true' >/dev/null
echo "OK fieldbus poll once"

TOKEN="$(curl -fsS -X POST http://127.0.0.1:18080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"bacnet-mqtt-ci-admin"}' \
  | jq -r '.token // .access_token // empty')"
if [[ -z "$TOKEN" ]]; then
  echo "FAIL: central login did not return a token" >&2
  "${COMPOSE[@]}" logs --tail=200 central >&2 || true
  exit 1
fi

# Wait until central has observed the fieldbus BACnet telemetry envelope.
deadline=$((SECONDS + 90))
while true; do
  MONITOR="$(curl -fsS http://127.0.0.1:18080/api/mqtt/monitor \
    -H "Authorization: Bearer $TOKEN")"
  if echo "$MONITOR" | jq -e '
      .connected == true and
      (.received_messages >= 1) and
      (.recent_messages | any(
        .topic == "openfdd/v1/sites/ci/edges/fieldbus-1/telemetry/bacnet" and
        (.payload_preview | contains("bacnet:3456:analog-value:1")) and
        (.payload_preview | contains("BUILDING_CI"))
      ))
    ' >/dev/null; then
    break
  fi
  if (( SECONDS >= deadline )); then
    echo "FAIL: central never observed expected BACnet telemetry" >&2
    echo "$MONITOR" | jq . >&2 || true
    "${COMPOSE[@]}" logs --tail=250 fieldbus central mqtt bacnet-sim >&2 || true
    exit 1
  fi
  sleep 3
done

echo "OK central observed canonical BACnet telemetry over MQTTS"
echo "$MONITOR" | jq '{connected, received_messages, errors, recent_messages: [.recent_messages[] | {topic, payload_bytes, payload_encoding}]}'
echo "PASS: BACpypes3 -> Open-FDD BACnet fieldbus -> MQTTS -> central integration"
