#!/usr/bin/env bash
# 3.3.31 — Disposable MQTTS transport isolation (cert trust, ACL deny, QoS).
# Pulls openfdd-mqtt from GHCR only. Tears down all containers/volumes on exit.
# Does NOT write to live Railway / OT brokers.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

TAG="${OPENFDD_IMAGE_TAG:?set OPENFDD_IMAGE_TAG to an immutable sha-<7> tag}"
if [[ ! "$TAG" =~ ^sha-[0-9a-f]{7}$ ]]; then
  echo "OPENFDD_IMAGE_TAG must match sha-<7 lowercase hex>, got: $TAG" >&2
  exit 1
fi

for cmd in docker openssl jq; do
  command -v "$cmd" >/dev/null || { echo "missing required command: $cmd" >&2; exit 1; }
done
docker info >/dev/null

ART="${ARTIFACT_DIR:-$ROOT/reports/waveC_mqtts_isolation_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$ART"
TMP="$(mktemp -d)"
NET="openfdd-mqtts-iso-${RANDOM}"
BROKER="openfdd-mqtts-iso-broker-${RANDOM}"
CLIENT="eclipse-mosquitto:2"
MQTT_IMAGE="ghcr.io/bbartling/openfdd-mqtt:${TAG}"

cleanup() {
  docker rm -f "$BROKER" "${BROKER}-sub1" "${BROKER}-sub2" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT

mkdir -p "$TMP/certs"
cat > "$TMP/certs/acl" <<'ACL'
user edge:site-a:fieldbus-1
topic write openfdd/v1/sites/site-a/edges/fieldbus-1/#
topic read openfdd/v1/sites/site-a/edges/fieldbus-1/commands/#

user edge:site-b:fieldbus-1
topic write openfdd/v1/sites/site-b/edges/fieldbus-1/#
topic read openfdd/v1/sites/site-b/edges/fieldbus-1/commands/#

user central:ci
topic read openfdd/v1/sites/#
topic write openfdd/v1/sites/+/edges/+/commands/#
ACL

openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
  -subj '/CN=openfdd-mqtts-iso-ca' \
  -keyout "$TMP/ca.key.pem" -out "$TMP/certs/ca.pem" >/dev/null 2>&1

# Foreign CA for negative trust test.
openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
  -subj '/CN=openfdd-mqtts-iso-foreign-ca' \
  -keyout "$TMP/foreign-ca.key.pem" -out "$TMP/foreign-ca.pem" >/dev/null 2>&1

issue_cert() {
  local name="$1" cn="$2" usage="$3" san="${4:-}" ca_pem="$5" ca_key="$6"
  local ext="$TMP/${name}.ext"
  {
    echo "extendedKeyUsage=${usage}"
    [[ -n "$san" ]] && echo "subjectAltName=${san}"
  } > "$ext"
  openssl req -newkey rsa:2048 -nodes -subj "/CN=${cn}" \
    -keyout "$TMP/${name}.key.pem" -out "$TMP/${name}.csr.pem" >/dev/null 2>&1
  openssl x509 -req -days 1 -sha256 \
    -in "$TMP/${name}.csr.pem" \
    -CA "$ca_pem" -CAkey "$ca_key" -CAcreateserial \
    -extfile "$ext" -out "$TMP/${name}.cert.pem" >/dev/null 2>&1
}

issue_cert server mqtt serverAuth 'DNS:mqtt,DNS:localhost' "$TMP/certs/ca.pem" "$TMP/ca.key.pem"
issue_cert edge_a 'edge:site-a:fieldbus-1' clientAuth '' "$TMP/certs/ca.pem" "$TMP/ca.key.pem"
issue_cert edge_b 'edge:site-b:fieldbus-1' clientAuth '' "$TMP/certs/ca.pem" "$TMP/ca.key.pem"
issue_cert central 'central:ci' clientAuth '' "$TMP/certs/ca.pem" "$TMP/ca.key.pem"
issue_cert edge_foreign 'edge:site-a:fieldbus-1' clientAuth '' "$TMP/foreign-ca.pem" "$TMP/foreign-ca.key.pem"

cp "$TMP/server.cert.pem" "$TMP/certs/server.cert.pem"
cp "$TMP/server.key.pem" "$TMP/certs/server.key.pem"
chmod 644 "$TMP/certs"/* "$TMP"/*.pem "$TMP"/*.key.pem 2>/dev/null || chmod 644 "$TMP/certs"/*

echo "== Pull mqtt image $TAG =="
docker pull "$MQTT_IMAGE" >/dev/null
docker pull "$CLIENT" >/dev/null

docker network create "$NET" >/dev/null
docker run -d --name "$BROKER" --network "$NET" --network-alias mqtt \
  -v "$TMP/certs:/mosquitto/certs:ro" \
  "$MQTT_IMAGE" >/dev/null

# Wait for broker listen (mosquitto has no HTTP health).
for _ in $(seq 1 30); do
  if docker logs "$BROKER" 2>&1 | grep -q 'opening ipv'; then
    break
  fi
  sleep 1
done

run_pub() {
  local name="$1" cert="$2" key="$3" ca="$4" topic="$5" payload="$6" qos="${7:-0}"
  docker run --rm --network "$NET" \
    -v "$TMP:/certs:ro" \
    "$CLIENT" mosquitto_pub \
    -h mqtt -p 8883 \
    --cafile "/certs/${ca}" \
    --cert "/certs/${cert}" \
    --key "/certs/${key}" \
    -t "$topic" -m "$payload" -q "$qos" \
    >/dev/null 2>"$ART/${name}.err" && echo ok || echo fail
}

# --- Case 1: allowed publish (site-a → site-a topic) delivered to central ---
: >"$ART/allow_same_site.payload"
docker run -d --name "${BROKER}-sub1" --network "$NET" \
  -v "$TMP:/certs:ro" \
  "$CLIENT" mosquitto_sub \
  -h mqtt -p 8883 \
  --cafile /certs/certs/ca.pem \
  --cert /certs/central.cert.pem \
  --key /certs/central.key.pem \
  -t 'openfdd/v1/sites/site-a/edges/fieldbus-1/telemetry/test' -C 1 \
  >/dev/null
sleep 1
c1_pub="$(run_pub allow_same_site edge_a.cert.pem edge_a.key.pem certs/ca.pem \
  'openfdd/v1/sites/site-a/edges/fieldbus-1/telemetry/test' 'iso-ok' 0)"
sleep 2
docker logs "${BROKER}-sub1" >"$ART/allow_same_site.payload" 2>/dev/null || true
docker rm -f "${BROKER}-sub1" >/dev/null 2>&1 || true
if [[ "$c1_pub" == "ok" ]] && grep -q 'iso-ok' "$ART/allow_same_site.payload"; then
  c1=ok
else
  c1=fail
fi
echo "case_allow_same_site=$c1 (pub=$c1_pub)" | tee "$ART/case_allow_same_site.txt"

# --- Case 2: ACL cross-site deny — site-a must NOT deliver to site-b topic ---
docker run -d --name "${BROKER}-sub2" --network "$NET" \
  -v "$TMP:/certs:ro" \
  "$CLIENT" mosquitto_sub \
  -h mqtt -p 8883 \
  --cafile /certs/certs/ca.pem \
  --cert /certs/central.cert.pem \
  --key /certs/central.key.pem \
  -t 'openfdd/v1/sites/site-b/edges/fieldbus-1/telemetry/test' -C 1 \
  >/dev/null
sleep 1
c2_pub="$(run_pub deny_cross_site edge_a.cert.pem edge_a.key.pem certs/ca.pem \
  'openfdd/v1/sites/site-b/edges/fieldbus-1/telemetry/test' 'should-deny' 0)"
sleep 2
docker logs "${BROKER}-sub2" >"$ART/deny_cross_site.payload" 2>/dev/null || true
docker rm -f "${BROKER}-sub2" >/dev/null 2>&1 || true
if grep -q 'should-deny' "$ART/deny_cross_site.payload" 2>/dev/null; then
  c2=fail  # message leaked — ACL broken
else
  c2=ok    # no delivery — deny proven (pub may still exit 0)
fi
echo "case_deny_cross_site=$c2 (pub=$c2_pub)" | tee "$ART/case_deny_cross_site.txt"

# --- Case 3: foreign CA / untrusted cert must fail TLS ---
c3="$(run_pub deny_foreign_ca edge_foreign.cert.pem edge_foreign.key.pem certs/ca.pem \
  'openfdd/v1/sites/site-a/edges/fieldbus-1/telemetry/test' 'untrusted' 0)"
# Expect publish attempt itself to fail (TLS verify).
if [[ "$c3" == "fail" ]]; then
  c3=ok
else
  c3=fail
fi
echo "case_deny_foreign_ca=$c3" | tee "$ART/case_deny_foreign_ca.txt"

# --- Case 4: QoS 1 publish succeeds on allowed topic ---
c4="$(run_pub qos1_allow edge_a.cert.pem edge_a.key.pem certs/ca.pem \
  'openfdd/v1/sites/site-a/edges/fieldbus-1/telemetry/qos' 'qos1-payload' 1)"
echo "case_qos1_allow=$c4" | tee "$ART/case_qos1_allow.txt"

# --- Case 5: reconnect — stop/start broker, allowed publish still works ---
docker stop "$BROKER" >/dev/null
docker start "$BROKER" >/dev/null
sleep 2
c5="$(run_pub reconnect_allow edge_a.cert.pem edge_a.key.pem certs/ca.pem \
  'openfdd/v1/sites/site-a/edges/fieldbus-1/telemetry/reconnect' 'after-restart' 0)"
echo "case_reconnect_allow=$c5" | tee "$ART/case_reconnect_allow.txt"

pass=1
[[ "$c1" == "ok" ]] || pass=0
[[ "$c2" == "ok" ]] || pass=0
[[ "$c3" == "ok" ]] || pass=0
[[ "$c4" == "ok" ]] || pass=0
[[ "$c5" == "ok" ]] || pass=0

jq -n \
  --arg tag "$TAG" \
  --arg art "$ART" \
  --argjson pass "$pass" \
  --arg c1 "$c1" --arg c2 "$c2" --arg c3 "$c3" --arg c4 "$c4" --arg c5 "$c5" \
  '{
    suite: "mqtts_transport_isolation_v1",
    image_tag: $tag,
    artifact_dir: $art,
    pass: ($pass == 1),
    cases: {
      allow_same_site: $c1,
      deny_cross_site: $c2,
      deny_foreign_ca: $c3,
      qos1_allow: $c4,
      reconnect_allow: $c5
    },
    notes: "Logical ACL/cert/QoS proofs on disposable broker; transport freshness separate from sensor freshness."
  }' | tee "$ART/verdict.json"

if [[ "$pass" != "1" ]]; then
  echo "FAIL: MQTTS transport isolation" >&2
  docker logs "$BROKER" 2>&1 | tail -80 | tee "$ART/broker.tail.log" >&2 || true
  exit 1
fi

echo "PASS: MQTTS transport isolation → $ART"
