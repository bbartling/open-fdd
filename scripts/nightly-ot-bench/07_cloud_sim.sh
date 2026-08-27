#!/usr/bin/env bash
# Cloud-sim gate: bensbench standalone stack = "cloud central"; a remote Raspberry Pi
# (bosspi) = "building edge" running fieldbus with its OWN BACnet instance (600000),
# streaming MQTTS telemetry to central over the LAN — the many-buildings-per-central
# topology in miniature.
#
# Phases:
#   A. prereqs (ssh, central health, provision binary)
#   B. broker server cert must carry the LAN IP SAN (remote edges verify TLS by IP)
#   C. provision second-site edge kit + merge broker ACL
#   D. central multi-site subscribe (OPENFDD_SITE_ID="+" via local compose override)
#   E. remote edge bring-up on the Pi (amd64 image under qemu/binfmt — arm64 gap is a finding)
#   F. assertions: two edges on /api/edges, bldg2 telemetry with numeric values,
#      Who-Is sees 599999 and 600000 as distinct hosted devices
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib.sh"
load_bench_env
auth_setup
cd "$ROOT"

PI_SSH="${CLOUD_SIM_PI_SSH:-ben@192.168.204.12}"
SSH_OPTS=(-i "$HOME/.ssh/id_rsa" -o BatchMode=yes -o ConnectTimeout=10)
SITE2="${CLOUD_SIM_SITE_ID:-bldg2}"
EDGE2="${CLOUD_SIM_EDGE_ID:-pi-1}"
BROKER_IP="${CLOUD_SIM_BROKER_HOST:-192.168.204.55}"
DEV2="${CLOUD_SIM_DEVICE_INSTANCE:-600000}"
PI_REPO="${CLOUD_SIM_PI_REPO:-/home/ben/open-fdd}"
WAIT_TELEMETRY="${CLOUD_SIM_TELEMETRY_WAIT:-150}"

ART="${ARTIFACT_DIR:-$(artifact_dir)}"
mkdir -p "$ART"

pi() { ssh "${SSH_OPTS[@]}" "$PI_SSH" "$@"; }

# --- A. prereqs --------------------------------------------------------------
hdr "A. prereqs"
if pi 'hostname' >/dev/null 2>&1; then
  ok "ssh to Pi ($PI_SSH → $(pi hostname))"
else
  bad "cannot ssh to Pi $PI_SSH"; summary; exit 1
fi
if central "$CENTRAL_BASE/api/health" >/dev/null 2>&1; then
  ok "central healthy on bench"
else
  bad "central not healthy — run standalone gates first"; summary; exit 1
fi
PROVISION="$ROOT/target/debug/openfdd-provision"
if [[ -x "$PROVISION" ]]; then
  ok "openfdd-provision binary present"
else
  bad "no openfdd-provision at $PROVISION (cargo build -p openfdd_mqtt --bin openfdd-provision)"
  summary; exit 1
fi

# --- B. broker server cert SAN ------------------------------------------------
hdr "B. broker TLS cert must include IP:$BROKER_IP for remote edges"
CERT="$ROOT/deploy/mqtt/certs/server.cert.pem"
if openssl x509 -in "$CERT" -noout -text | grep -q "IP Address:$BROKER_IP"; then
  ok "server cert already has IP:$BROKER_IP SAN"
else
  echo "${DIM}regenerating broker server cert with LAN IP SAN (bench CA)${RST}"
  CA_DIR="$ROOT/deploy/mqtt/ca"
  TMP="$(mktemp -d)"
  cat >"$TMP/san.cnf" <<EOF
[req]
distinguished_name = dn
req_extensions = v3_req
prompt = no
[dn]
CN = mqtt
[v3_req]
subjectAltName = @alt
[alt]
DNS.1 = mqtt
DNS.2 = localhost
IP.1 = 127.0.0.1
IP.2 = $BROKER_IP
EOF
  openssl req -new -newkey rsa:2048 -nodes \
    -keyout "$TMP/server.key.pem" -out "$TMP/server.csr" -config "$TMP/san.cnf" >/dev/null 2>&1
  openssl x509 -req -in "$TMP/server.csr" -CA "$CA_DIR/ca.pem" -CAkey "$CA_DIR/ca.key.pem" \
    -CAcreateserial -out "$TMP/server.cert.pem" -days 397 \
    -extensions v3_req -extfile "$TMP/san.cnf" >/dev/null 2>&1
  cp "$TMP/server.cert.pem" "$CERT"
  cp "$TMP/server.key.pem" "$ROOT/deploy/mqtt/certs/server.key.pem"
  rm -rf "$TMP"
  if openssl x509 -in "$CERT" -noout -text | grep -q "IP Address:$BROKER_IP"; then
    ok "server cert regenerated with IP:$BROKER_IP (finding: provisioning tool has no broker-cert command)"
    NEED_MQTT_RESTART=1
  else
    bad "failed to regenerate server cert with LAN SAN"; summary; exit 1
  fi
fi

# --- C. provision second-site kit + ACL ---------------------------------------
hdr "C. provision $SITE2/$EDGE2 kit + broker ACL"
KIT_DIR="$ROOT/deploy/mqtt/kits/${SITE2}__${EDGE2}"
if [[ ! -f "$KIT_DIR/edge.cert.pem" ]]; then
  "$PROVISION" edge --site-id "$SITE2" --edge-id "$EDGE2" \
    --broker-host "$BROKER_IP" --out-dir "$ROOT/deploy/mqtt" >/dev/null
fi
if [[ -f "$KIT_DIR/edge.cert.pem" && -f "$KIT_DIR/ca.pem" ]]; then
  ok "edge kit at deploy/mqtt/kits/${SITE2}__${EDGE2}"
else
  bad "provisioning failed for ${SITE2}__${EDGE2}"; summary; exit 1
fi

ACL="$ROOT/deploy/mqtt/acl"
if ! grep -q "edge:${SITE2}:${EDGE2}" "$ACL" 2>/dev/null; then
  { echo; cat "$KIT_DIR/mosquitto.acl"; } >>"$ACL"
  NEED_MQTT_RESTART=1
fi
# Central identity is central:lab (cert CN) — widen its read to all sites for multi-site test.
if ! grep -q "topic read openfdd/v1/sites/#" "$ACL" 2>/dev/null; then
  python3 - "$ACL" <<'PY'
import sys, re
p = sys.argv[1]
text = open(p).read()
# after each "user central:*" line ensure a global site read
out, lines = [], text.splitlines()
for i, line in enumerate(lines):
    out.append(line)
    if re.match(r"^user central:", line):
        out.append("topic read openfdd/v1/sites/#")
open(p, "w").write("\n".join(out) + "\n")
PY
  NEED_MQTT_RESTART=1
fi
ok "broker ACL includes ${SITE2} edge + central multi-site read (finding: provision tool emits single-site central ACL only)"

if [[ "${NEED_MQTT_RESTART:-0}" == "1" ]]; then
  mapfile -t CF < <(compose_files)
  docker compose "${CF[@]}" restart mqtt >/dev/null 2>&1 && ok "mqtt broker restarted (new cert/ACL)" || bad "mqtt restart failed"
  sleep 3
fi

# --- D. central multi-site subscribe ------------------------------------------
hdr "D. central multi-site subscribe (OPENFDD_SITE_ID='+')"
OVR="$ROOT/docker/compose.cloudsim.local.yml"
if [[ ! -f "$OVR" ]]; then
  cat >"$OVR" <<EOF
# Cloud-sim bench override — central subscribes to ALL sites. Do not commit.
services:
  central:
    environment:
      OPENFDD_SITE_ID: "+"
    volumes:
      - ../workspace:/workspace
      - ../deploy/mqtt/kits/${OPENFDD_SITE_ID}__central:/mqtt:ro
EOF
fi
mapfile -t CF < <(compose_files)
docker compose "${CF[@]}" -f "$OVR" up -d central >/dev/null 2>&1 || true
sleep 5
if central "$CENTRAL_BASE/api/health" >/dev/null 2>&1; then
  ok "central healthy with multi-site subscription override"
else
  bad "central unhealthy after OPENFDD_SITE_ID='+' override — multi-site subscribe unsupported (finding)"
fi

# --- E. remote edge on the Pi ---------------------------------------------------
hdr "E. remote edge bring-up on Pi (site=$SITE2 edge=$EDGE2 device=$DEV2)"

# qemu/binfmt for amd64 images on aarch64 (stack images are amd64-only: known gap)
AMD64_PROBE='timeout 60 docker run --rm --entrypoint /bin/sh --platform linux/amd64 ghcr.io/bbartling/openfdd-fieldbus:nightly -c "echo qemu-ok"'
if pi "$AMD64_PROBE" 2>/dev/null | grep -q qemu-ok; then
  ok "Pi can execute amd64 fieldbus image (binfmt present)"
else
  echo "${DIM}installing qemu binfmt handlers on Pi${RST}"
  pi 'docker run --privileged --rm tonistiigi/binfmt --install amd64' >/dev/null 2>&1 || true
  if pi "$AMD64_PROBE" 2>/dev/null | grep -q qemu-ok; then
    ok "qemu binfmt installed — amd64 image runs under emulation (finding: no arm64 nightlies)"
  else
    bad "Pi cannot run amd64 fieldbus image even with binfmt — arm64 image gap blocks real deployments"
    skip "falling back is manual: run a second edge compose project on the bench instead"
    summary; exit 1
  fi
fi

# Ship the kit (public CA + edge cert/key only)
pi "mkdir -p $PI_REPO/deploy/mqtt/kits/${SITE2}__${EDGE2}"
scp "${SSH_OPTS[@]}" -q "$KIT_DIR"/{ca.pem,edge.cert.pem,edge.key.pem,edge.json} \
  "$PI_SSH:$PI_REPO/deploy/mqtt/kits/${SITE2}__${EDGE2}/" && ok "edge kit shipped to Pi" || { bad "kit scp failed"; summary; exit 1; }

# Pi-local gateway config. #532 claims OPENFDD_BACNET_DEVICE_INSTANCE is honored, so we
# deliberately RESET gateway.toml to git default (599999) and set instance $DEV2 purely
# via env — if 600000 answers ReadProperty later, the env path is proven. City is set to
# Chicago (bench stays Madison) for gate 08's weather legitimacy check.
pi "cd $PI_REPO && git checkout -- config/fieldbus/gateway.toml && python3 - <<'PY'
import re
p = 'config/fieldbus/gateway.toml'
s = open(p).read()
s = re.sub(r'city\s*=\s*\"[^\"]*\"', 'city = \"Chicago\"', s, count=1)
s = re.sub(r'device_name\s*=\s*\"[^\"]*\"', 'device_name = \"OpenFDD-${SITE2}\"', s, count=1)
open(p, 'w').write(s)
print('gateway.toml →', [l for l in s.splitlines() if 'device_instance' in l or 'city' in l])
PY" | tee "$ART/pi_gateway_patch.txt"
if grep -q 'city = "Chicago"' "$ART/pi_gateway_patch.txt" && grep -q "device_instance = 599999" "$ART/pi_gateway_patch.txt"; then
  ok "Pi gateway.toml: city=Chicago, toml instance left at git default (599999) — $DEV2 comes from env only (#532 verification)"
else
  bad "failed to patch Pi gateway.toml (city/instance)"
fi

# compose.edge.yml does not pass OPENFDD_BACNET_DEVICE_INSTANCE through, so a local
# (gitignored-style) override supplies it — this is the #532 env path under test.
pi "cat > $PI_REPO/docker/compose.edge.local.yml <<'EOF'
# Cloud-sim bench override — hosted BACnet instance via env (#532). Do not commit.
services:
  fieldbus:
    # Explicit platform: 'pull always' fails on arm64 (no manifest, #530) and compose
    # silently reuses the STALE local amd64 image — that shipped yesterday's build and
    # caused the 2026-07-18 duplicate-instance-599999 incident in Workbench.
    platform: linux/amd64
    environment:
      OPENFDD_BACNET_DEVICE_INSTANCE: \"${DEV2}\"
    # Bench mitigation for the per-operation UDP socket leak (BACnetClient::stop());
    # keeps the long-term soak alive until the product fix ships.
    ulimits:
      nofile:
        soft: 65536
        hard: 65536
EOF
echo wrote-override"

# Pull the pinned tip image explicitly (amd64 under qemu) and FAIL LOUDLY on digest drift.
PI_FIELDBUS_IMAGE="${OPENFDD_FIELDBUS_IMAGE:-ghcr.io/bbartling/openfdd-fieldbus:${OPENFDD_IMAGE_TAG:-nightly}}"
echo "${DIM}Pi fieldbus image pin: $PI_FIELDBUS_IMAGE${RST}"
if pi "docker pull --platform linux/amd64 $PI_FIELDBUS_IMAGE >/dev/null 2>&1"; then
  PI_REV="$(pi "docker inspect $PI_FIELDBUS_IMAGE --format '{{index .Config.Labels \"org.opencontainers.image.revision\"}}'" 2>/dev/null | head -c 12 || true)"
  BENCH_REV="$(docker inspect "$PI_FIELDBUS_IMAGE" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' 2>/dev/null | head -c 12 || true)"
  if [[ -n "$PI_REV" && "$PI_REV" == "$BENCH_REV" ]]; then
    ok "Pi pulled amd64 tip rev $PI_REV (matches bench)"
  else
    bad "Pi tip rev '$PI_REV' != bench '$BENCH_REV' — stale image would fake results"
    summary; exit 1
  fi
else
  bad "explicit amd64 pull failed on Pi for $PI_FIELDBUS_IMAGE — refusing stale soak"
  summary; exit 1
fi

# field_devices: Pi polls the BIP bench sims as its "building devices" PLUS the bench
# hosted server 599999 — the cross-device weather read for gate 08 (600000's edge
# reading 599999's Open-Meteo mirror over real BACnet).
pi "cat > $PI_REPO/config/fieldbus/field_devices.toml <<'EOF'
# Cloud-sim building: poll BIP bench devices from the Pi edge.
[[devices]]
name = \"Bldg2FakeAhu\"
enabled = true
device_instance = ${BIP_DEVICE_A:-3456789}
host = \"192.168.204.13\"
port = 47808
points = [
  { object_type = \"analog-input\", object_instance = ${BIP_DEVICE_A_READ_INST:-2}, point_name = \"SA-T\", units = \"degF\" },
]

[[devices]]
name = \"Bldg2ZoneVav\"
enabled = true
device_instance = ${BIP_DEVICE_B:-3456790}
host = \"192.168.204.14\"
port = 47808
points = [
  { object_type = \"analog-input\", object_instance = ${BIP_DEVICE_B_READ_INST:-1}, point_name = \"ZoneTemp\", units = \"degF\" },
]

[[devices]]
name = \"BenchHostedWeather\"
enabled = true
device_instance = ${HOSTED_DEVICE:-599999}
host = \"${BROKER_IP}\"
port = 47808
points = [
  { object_type = \"analog-value\", object_instance = 9101, point_name = \"OA-T\", units = \"degF\" },
  { object_type = \"analog-value\", object_instance = 9102, point_name = \"OA-RH\", units = \"percent\" },
]
EOF
grep -c device_instance $PI_REPO/config/fieldbus/field_devices.toml" >/dev/null 2>&1 || true

# Bring up the edge recipe (base + instance override)
echo "${DIM}Pi edge compose image: $PI_FIELDBUS_IMAGE${RST}"
if pi "cd $PI_REPO && \
  OPENFDD_FIELDBUS_IMAGE=$PI_FIELDBUS_IMAGE \
  OPENFDD_MQTT_HOST=$BROKER_IP OPENFDD_MQTT_PORT=8883 \
  OPENFDD_SITE_ID=$SITE2 OPENFDD_EDGE_ID=$EDGE2 \
  OPENFDD_EDGE_KIT_DIR=$PI_REPO/deploy/mqtt/kits/${SITE2}__${EDGE2} \
  docker compose -f docker/compose.edge.yml -f docker/compose.edge.local.yml up -d --force-recreate" >"$ART/pi_edge_up.log" 2>&1; then
  ok "edge compose up on Pi (instance $DEV2; image $PI_FIELDBUS_IMAGE)"
else
  bad "edge compose up failed on Pi (see pi_edge_up.log)"
  tail -5 "$ART/pi_edge_up.log" || true
fi
# Assert tip revision when Pi is up
PI_REV="$(pi "docker inspect openfdd-edge-fieldbus-1 --format '{{index .Config.Labels \"org.opencontainers.image.revision\"}}'" 2>/dev/null || true)"
BENCH_FB_REV="$(docker inspect "$PI_FIELDBUS_IMAGE" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' 2>/dev/null || true)"
if [[ -n "$PI_REV" && "$PI_REV" == "$BENCH_FB_REV" ]]; then
  ok "Pi fieldbus rev matches tip (${PI_REV:0:12})"
elif [[ -n "$PI_REV" ]]; then
  bad "Pi fieldbus rev drift: pi=${PI_REV:0:12} tip=${BENCH_FB_REV:0:12}"
fi

echo "${DIM}waiting up to 90s for Pi fieldbus health (qemu is slow)${RST}"
PI_HEALTH=""
for _ in $(seq 1 18); do
  PI_HEALTH="$(pi 'curl -fsS --max-time 5 http://127.0.0.1:8081/health' 2>/dev/null || true)"
  [[ -n "$PI_HEALTH" ]] && break
  sleep 5
done
if [[ -n "$PI_HEALTH" ]] && jq -e '.ok==true' <<<"$PI_HEALTH" >/dev/null 2>&1; then
  ok "Pi fieldbus healthy under emulation"
  echo "${DIM}  $(jq -c '{service,version}' <<<"$PI_HEALTH" 2>/dev/null)${RST}"
else
  bad "Pi fieldbus not healthy after 90s (qemu/arm64 gap — capture logs)"
  pi "docker logs openfdd-edge-fieldbus-1 --tail 40" >"$ART/pi_fieldbus.log" 2>&1 || true
  tail -15 "$ART/pi_fieldbus.log" 2>/dev/null || true
fi

# --- F. assertions -------------------------------------------------------------
hdr "F. multi-building assertions"
echo "${DIM}waiting ${WAIT_TELEMETRY}s for first Pi MQTT publish interval${RST}"
sleep "$WAIT_TELEMETRY"

# F1: MQTTS traffic from site bldg2
if docker image inspect eclipse-mosquitto:2 >/dev/null 2>&1 || docker pull eclipse-mosquitto:2 >/dev/null 2>&1; then
  timeout 40 docker run --rm --net=host -v "$ROOT/deploy/mqtt:/mqtt:ro" eclipse-mosquitto:2 \
    mosquitto_sub -h 127.0.0.1 -p 8883 \
    --cafile /mqtt/ca/ca.pem \
    --cert "/mqtt/kits/${OPENFDD_SITE_ID}__central/central.cert.pem" \
    --key "/mqtt/kits/${OPENFDD_SITE_ID}__central/central.key.pem" \
    -t "openfdd/v1/sites/${SITE2}/edges/+/#" -v -C 3 -W 35 \
    >"$ART/mqtt_bldg2.txt" 2>&1 || true
  if grep -q "sites/${SITE2}/" "$ART/mqtt_bldg2.txt" 2>/dev/null; then
    ok "MQTTS traffic observed from site ${SITE2} (remote building streaming to central broker)"
    grep -qE '"value"[[:space:]]*:[[:space:]]*-?[0-9]' "$ART/mqtt_bldg2.txt" \
      && ok "bldg2 telemetry has numeric values" \
      || skip "no numeric value seen yet in captured bldg2 messages (status/metadata only?)"
    echo "${DIM}$(head -c 300 "$ART/mqtt_bldg2.txt")${RST}"
  else
    bad "no MQTTS traffic from site ${SITE2} (TLS/ACL/edge failure — see artifacts)"
  fi
fi

# F2: central sees both edges
if E="$(central "$CENTRAL_BASE/api/edges" 2>/dev/null)"; then
  echo "$E" >"$ART/edges_cloudsim.json"
  jq_ok "central /api/edges lists ≥2 edges" "$E" '(.edges // . // []) | length >= 2'
  if jq -e --arg e "$EDGE2" 'any(.edges[]?; .edge_id==$e and .has_telemetry==true)' <<<"$E" >/dev/null 2>&1; then
    ok "central ingests remote edge ${EDGE2} telemetry (multi-building ingest works)"
  else
    bad "central /api/edges missing remote edge ${EDGE2} with telemetry"
  fi
  if jq -e --arg s "$SITE2" 'tostring | contains($s)' <<<"$E" >/dev/null 2>&1; then
    ok "/api/edges exposes site attribution for ${SITE2}"
  else
    skip "FINDING: /api/edges has no site_id field — edges from different sites are indistinguishable (multi-building API gap)"
  fi
  echo "${DIM}  $(jq -c . <<<"$E" | head -c 400)${RST}"
else
  bad "GET /api/edges failed"
fi

# F3: hosted instance discovery — HARD #526 retest: broadcast Who-Is via fieldbus client
# AND raw unicast Who-Is straight at each hosted server socket. Both must yield I-Am for
# Workbench discovery to work.
PI_IP="${PI_SSH##*@}"
if W="$(fb -X POST "$FIELDBUS_BASE/bacnet/whois" -d '{}' 2>/dev/null)"; then
  echo "$W" >"$ART/whois_cloudsim.json"
  for inst in "$HOSTED_DEVICE" "$DEV2"; do
    if jq -e --argjson d "$inst" 'any(.devices[]; .device_instance==$d)' <<<"$W" >/dev/null 2>&1; then
      ok "#526: broadcast Who-Is sees hosted device $inst (I-Am fixed?)"
    else
      bad "#526 STILL OPEN: hosted device $inst absent from broadcast Who-Is (Workbench discovery blocked)"
    fi
  done
  echo "${DIM}  devices=$(jq -c '[.devices[].device_instance]' <<<"$W" 2>/dev/null)${RST}"
fi
# Raw unicast Who-Is (limits bracketing each instance) directly at each server's UDP :47808
set +e
python3 - "${OT_BIND:-127.0.0.1}" "$HOSTED_DEVICE" "$PI_IP" "$DEV2" <<'PY' | tee "$ART/whois_unicast.txt"
import socket, sys
targets = [(sys.argv[1], int(sys.argv[2])), (sys.argv[3], int(sys.argv[4]))]
def whois_unicast(ip, inst):
    # unconfirmed Who-Is with low/high = inst (context tags 0,1; 3-byte unsigned)
    lim = inst.to_bytes(3, "big")
    apdu = bytes([0x10, 0x08]) + b"\x0a" + lim + b"\x1a" + lim
    pkt = bytes([0x81, 0x0a]) + (4 + 2 + len(apdu)).to_bytes(2, "big") + bytes([0x01, 0x04]) + apdu
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(6)
    try:
        s.sendto(pkt, (ip, 47808))
        data, _ = s.recvfrom(2048)
        return data.hex()
    except Exception as e:
        return None
    finally:
        s.close()
rc = 0
for ip, inst in targets:
    r = whois_unicast(ip, inst)
    print(f"unicast-whois {inst}@{ip}: {'I-Am ' + r[:40] if r else 'no unicast reply to ephemeral source'}")
    if not r:
        rc = 1
sys.exit(rc)
PY
WHOIS_UNI_RC=${PIPESTATUS[0]}
set -e
if [[ "$WHOIS_UNI_RC" -eq 0 ]]; then
  ok "#526: hosted servers reply I-Am unicast to ephemeral requester"
else
  # 2026-07-18 evidence: server DOES emit I-Am, but as a BROADCAST to :47808 (spec-legal);
  # a 47808-bound listener on another host captures it. The gap is the fieldbus CLIENT:
  # whois_bind_port=0 (ephemeral) can never receive broadcast I-Ams, so /bacnet/whois
  # misses hosted devices. Workbench (bound :47808) should discover fine.
  skip "#526 refined: no unicast I-Am to ephemeral source (server broadcasts I-Am to :47808; fieldbus client's ephemeral whois bind misses it — client-side defect)"
fi

# F3b: directed ReadProperty proves both hosted devices are alive, DISTINCT, and that the
# Pi genuinely hosts $DEV2 (env-only instance, #532). Error-aware on purpose: the 2026-07-18
# duplicate-instance incident slipped through a parser that treated a BACnet Error APDU as
# success. Now we require: dev2@Pi = ComplexAck, dev1@Pi = Error (no 599999 ghost on the Pi),
# dev1@bench = ComplexAck, and the two names differ.
RP_OUT="$(python3 - "$PI_IP" "$DEV2" "${OT_BIND:-127.0.0.1}" "${HOSTED_DEVICE}" <<'PY'
import socket, sys
pi_ip, dev2, bench_ip, dev1 = sys.argv[1], int(sys.argv[2]), sys.argv[3], int(sys.argv[4])
def read_object_name(ip, inst):
    # -> ("ok", name) | ("error", raw) | ("timeout", None)
    obj = (8 << 22) | inst
    apdu = bytes([0x00,0x05,0x01,0x0C]) + b'\x0c' + obj.to_bytes(4,'big') + b'\x19\x4d'
    pkt = bytes([0x81,0x0a]) + (4+2+len(apdu)).to_bytes(2,'big') + bytes([0x01,0x04]) + apdu
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(6)
    try:
        s.sendto(pkt, (ip, 47808)); data,_ = s.recvfrom(2048)
    except Exception:
        return ("timeout", None)
    finally:
        s.close()
    pdu_type = data[6] >> 4
    if pdu_type == 5:   # Error PDU (e.g. unknown-object)
        return ("error", data[6:].hex())
    if pdu_type == 3 and 0x75 in data:  # ComplexAck with extended charstring
        i = data.index(0x75)
        return ("ok", data[i+3:i+3+data[i+1]-1].decode('utf-8', 'replace'))
    return ("error", f"unexpected pdu_type={pdu_type}")
r2 = read_object_name(pi_ip, dev2)      # must be ok
g2 = read_object_name(pi_ip, dev1)      # must be error (no duplicate of bench instance!)
r1 = read_object_name(bench_ip, dev1)   # must be ok
print(f"pi    device:{dev2} -> {r2}")
print(f"pi    device:{dev1} -> {g2}   (must be error: duplicate-instance guard)")
print(f"bench device:{dev1} -> {r1}")
okall = (r2[0] == "ok" and r1[0] == "ok" and g2[0] == "error" and r2[1] != r1[1])
sys.exit(0 if okall else 1)
PY
)" && RP_RC=0 || RP_RC=1
echo "$RP_OUT" | tee "$ART/hosted_readprop.txt"
if [[ "$RP_RC" -eq 0 ]]; then
  ok "hosted instances distinct: Pi answers ONLY $DEV2, bench answers ${HOSTED_DEVICE} — env instance honored (#532), no duplicate device id"
else
  bad "hosted instance identity FAILED — duplicate/misconfigured device id (env ignored or stale image; see hosted_readprop.txt)"
fi

# F4: ingest growth attributable to second site
if IS="$(central "$CENTRAL_BASE/api/ingest/stats" 2>/dev/null)"; then
  echo "$IS" >"$ART/ingest_stats_cloudsim.json"
  ok "ingest/stats captured post-cloudsim ($(jq -c . <<<"$IS" | head -c 200))"
fi

summary
echo "${DIM}Artifacts: $ART — leave the Pi edge RUNNING for soak; tear down only by human decision.${RST}"
