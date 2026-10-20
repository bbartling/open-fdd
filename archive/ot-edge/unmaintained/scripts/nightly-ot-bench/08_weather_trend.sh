#!/usr/bin/env bash
# Weather trend + long-term soak gate — proves the hosted BACnet servers serve LIVE,
# UPDATING Open-Meteo data (not the 70.0/50.0 fallback frozen values seen in Workbench
# on 2026-07-17).
#
# Topology under test:
#   599999 @ bench (Madison Wisconsin)   — standalone stack fieldbus
#   600000 @ Pi    (Chicago)             — cloud-sim edge (gate 07 sets city=Chicago)
#
# Phases:
#   A. BEFORE snapshot — /weather API + directed BACnet ReadProperty (AV:9101 temp,
#      AV:9102 RH, CSV:9107 last-updated, BV:9106 app-fault) on BOTH devices
#   B. Cross-device read — the Pi's 600000 edge reads 599999's weather points over
#      real BACnet (device 599999 is in the Pi's field_devices.toml, gate 07)
#   C. Soak — WEATHER_SOAK_SECS (default 1800) with a sample every WEATHER_SAMPLE_SECS
#      (default 300) → trend CSV artifact for the report
#   D. AFTER snapshot — assert weather-last-updated CHANGED on both devices and values
#      are NOT stuck at fallback (app-fault BV inactive, from_api=true)
#   E. Legitimacy — python fetches real Open-Meteo Chicago + Madison current temps from
#      the host and asserts each device matches its city within ±3 °F
#   F. Root-cause on failure — docker exec DNS/HTTPS probe to open-meteo from inside
#      the fieldbus container(s)
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib.sh"
load_bench_env
auth_setup
cd "$ROOT"

PI_SSH="${CLOUD_SIM_PI_SSH:-ben@192.168.204.12}"
SSH_OPTS=(-i "$HOME/.ssh/id_rsa" -o BatchMode=yes -o ConnectTimeout=10)
PI_IP="${PI_SSH##*@}"
BENCH_IP="${OT_BIND:-127.0.0.1}"
DEV1="${HOSTED_DEVICE:-599999}"
DEV2="${CLOUD_SIM_DEVICE_INSTANCE:-600000}"
SOAK="${WEATHER_SOAK_SECS:-1800}"
SAMPLE_EVERY="${WEATHER_SAMPLE_SECS:-300}"

ART="${ARTIFACT_DIR:-$(artifact_dir)}"
mkdir -p "$ART"
TREND="$ART/weather_trend.csv"

pi() { ssh "${SSH_OPTS[@]}" "$PI_SSH" "$@"; }

PI_UP=0
if pi 'curl -fsS --max-time 5 http://127.0.0.1:8081/health' 2>/dev/null | jq -e '.ok==true' >/dev/null 2>&1; then
  PI_UP=1
fi

# rp <ip> <device_instance> <object_type:AV|CSV|BV> <object_instance>
# Directed BACnet ReadProperty of present-value; prints decoded value or "ERR".
rp() {
  python3 - "$1" "$2" "$3" "$4" <<'PY'
import socket, struct, sys
ip, inst, otype, oinst = sys.argv[1], int(sys.argv[2]), sys.argv[3], int(sys.argv[4])
OT = {"AV": 2, "CSV": 40, "BV": 5}[otype]
obj = (OT << 22) | oinst
# ReadProperty (service 12): ctx0 objid, ctx1 property 85 (present-value)
apdu = bytes([0x00, 0x05, 0x01, 0x0C]) + b"\x0c" + obj.to_bytes(4, "big") + b"\x19\x55"
pkt = bytes([0x81, 0x0a]) + (4 + 2 + len(apdu)).to_bytes(2, "big") + bytes([0x01, 0x04]) + apdu
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(8)
try:
    s.sendto(pkt, (ip, 47808))
    data, _ = s.recvfrom(2048)
except Exception as e:
    print("ERR"); sys.exit(1)
finally:
    s.close()
# ComplexAck: value sits inside opening/closing context tag 3 (0x3e ... 0x3f)
try:
    i = data.index(0x3e) + 1
    tag = data[i]
    cls, ln = tag >> 4, tag & 0x07
    if tag == 0x44:  # Real
        print(round(struct.unpack(">f", data[i+1:i+5])[0], 2))
    elif cls == 7:  # CharacterString
        if ln == 5:  # extended length in next byte
            length = data[i+1]; body = data[i+2:i+2+length]
        else:
            length = ln; body = data[i+1:i+1+length]
        print(body[1:].decode("utf-8", "replace"))  # first byte = charset
    elif cls == 9:  # Enumerated (BV)
        length = ln
        print(int.from_bytes(data[i+1:i+1+length], "big"))
    else:
        print(f"tag0x{tag:02x}:" + data[i:i+12].hex())
except ValueError:
    print("ERR"); sys.exit(1)
PY
}

snapshot() {
  # snapshot <label> — prints "temp|rh|stamp|fault" for dev1 and dev2 to stdout,
  # saves a readable block to the artifact dir.
  local label="$1" out="$ART/weather_snapshot_${1}.txt"
  {
    echo "== $label $(date -u +%FT%TZ) =="
    for spec in "bench:$BENCH_IP:$DEV1" "pi:$PI_IP:$DEV2"; do
      IFS=':' read -r name ip dev <<<"$spec"
      if [[ "$name" == "pi" && "$PI_UP" != "1" ]]; then
        echo "$name dev=$dev SKIPPED (pi edge not up)"
        continue
      fi
      local t rh st flt
      t="$(rp "$ip" "$dev" AV 9101 2>/dev/null || echo ERR)"
      rh="$(rp "$ip" "$dev" AV 9102 2>/dev/null || echo ERR)"
      st="$(rp "$ip" "$dev" CSV 9107 2>/dev/null || echo ERR)"
      flt="$(rp "$ip" "$dev" BV 9106 2>/dev/null || echo ERR)"
      echo "$name dev=$dev temp_f=$t rh=$rh app_fault=$flt last_updated='$st'"
    done
  } | tee "$out"
}

extract() {
  # extract <snapshot-file> <bench|pi> <field: temp_f|rh|app_fault|last_updated>
  local f="$1" who="$2" field="$3"
  if [[ "$field" == "last_updated" ]]; then
    grep "^$who " "$f" | sed -n "s/.*last_updated='\(.*\)'$/\1/p"
  else
    grep "^$who " "$f" | grep -o "${field}=[^ ]*" | cut -d= -f2
  fi
}

# --- A0. device identity guard ---------------------------------------------------
# Weather objects (AV/CSV/BV) answer regardless of the DEVICE instance, so before
# trusting any read, prove each host actually hosts ITS OWN device object and NOT the
# other one. Catches the duplicate-instance-599999 regression seen in Workbench.
hdr "A0. device identity ($DEV1 only on bench, $DEV2 only on Pi)"
devcheck() {
  # devcheck <ip> <instance> -> "ok:<name>" | "error" | "timeout"
  python3 - "$1" "$2" <<'PY'
import socket, sys
ip, inst = sys.argv[1], int(sys.argv[2])
obj = (8 << 22) | inst
apdu = bytes([0x00,0x05,0x01,0x0C]) + b'\x0c' + obj.to_bytes(4,'big') + b'\x19\x4d'
pkt = bytes([0x81,0x0a]) + (6+len(apdu)).to_bytes(2,'big') + bytes([0x01,0x04]) + apdu
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(6)
try:
    s.sendto(pkt, (ip, 47808)); d,_ = s.recvfrom(2048)
except Exception:
    print("timeout"); sys.exit(0)
finally:
    s.close()
t = d[6] >> 4
if t == 3 and 0x75 in d:
    i = d.index(0x75)
    print("ok:" + d[i+3:i+3+d[i+1]-1].decode('utf-8','replace'))
else:
    print("error")
PY
}
ID_B1="$(devcheck "$BENCH_IP" "$DEV1")"; ID_B2="$(devcheck "$BENCH_IP" "$DEV2")"
echo "bench device:$DEV1 -> $ID_B1 ; device:$DEV2 -> $ID_B2" | tee "$ART/device_identity.txt"
if [[ "$ID_B1" == ok:* && "$ID_B2" == "error" ]]; then
  ok "bench hosts ONLY device $DEV1 (${ID_B1#ok:})"
else
  bad "bench device identity wrong (dev$DEV1=$ID_B1 dev$DEV2=$ID_B2) — duplicate/misconfigured instance"
fi
if [[ "$PI_UP" == "1" ]]; then
  ID_P2="$(devcheck "$PI_IP" "$DEV2")"; ID_P1="$(devcheck "$PI_IP" "$DEV1")"
  echo "pi device:$DEV2 -> $ID_P2 ; device:$DEV1 -> $ID_P1" | tee -a "$ART/device_identity.txt"
  if [[ "$ID_P2" == ok:* && "$ID_P1" == "error" ]]; then
    ok "pi hosts ONLY device $DEV2 (${ID_P2#ok:}) — no duplicate of $DEV1 on the LAN"
  else
    bad "pi device identity wrong (dev$DEV2=$ID_P2 dev$DEV1=$ID_P1) — DUPLICATE INSTANCE, Workbench discovery will collide"
  fi
fi

# --- A. BEFORE snapshot --------------------------------------------------------
hdr "A. BEFORE snapshot (BACnet ReadProperty on $DEV1@$BENCH_IP and $DEV2@$PI_IP)"
snapshot before >/dev/null
BEFORE="$ART/weather_snapshot_before.txt"
B_T1="$(extract "$BEFORE" bench temp_f || true)"; B_ST1="$(extract "$BEFORE" bench last_updated || true)"
B_T2="$(extract "$BEFORE" pi temp_f || true)";    B_ST2="$(extract "$BEFORE" pi last_updated || true)"
[[ "$B_T1" != "ERR" && -n "$B_T1" ]] && ok "599999 answers weather ReadProperty (temp_f=$B_T1)" \
  || bad "599999 ReadProperty failed for AV:9101"
if [[ "$PI_UP" == "1" ]]; then
  [[ "$B_T2" != "ERR" && -n "$B_T2" ]] && ok "600000 answers weather ReadProperty (temp_f=$B_T2)" \
    || bad "600000 ReadProperty failed for AV:9101"
else
  skip "Pi edge not up — 600000 checks skipped (run gate 07 first)"
fi

# /weather API view (from_api truthfulness) on both fieldbuses
WB="$(fb "$FIELDBUS_BASE/weather" 2>/dev/null || echo '{}')"
echo "$WB" >"$ART/weather_api_bench_before.json"
echo "${DIM}  bench /weather: $(jq -c '{location,temp_f,from_api,reason}' <<<"$WB" 2>/dev/null)${RST}"
if [[ "$PI_UP" == "1" ]]; then
  WP="$(pi 'curl -fsS --max-time 10 http://127.0.0.1:8081/weather' 2>/dev/null || echo '{}')"
  echo "$WP" >"$ART/weather_api_pi_before.json"
  echo "${DIM}  pi    /weather: $(jq -c '{location,temp_f,from_api,reason}' <<<"$WP" 2>/dev/null)${RST}"
  if jq -e '.location | test("Chicago")' <<<"$WP" >/dev/null 2>&1; then
    ok "Pi weather city is Chicago (gate 07 config applied)"
  else
    bad "Pi weather location is not Chicago: $(jq -r '.location // "?"' <<<"$WP")"
  fi
fi

# --- B. cross-device read: 600000's edge reads 599999 over real BACnet ---------
hdr "B. cross-device read (Pi edge → 599999 weather points over BACnet)"
if [[ "$PI_UP" == "1" ]]; then
  XD="$(pi "curl -fsS --max-time 30 -X POST http://127.0.0.1:8081/bacnet/read \
    -H 'Content-Type: application/json' \
    -d '{\"device_instance\":$DEV1,\"object_type\":\"analog-value\",\"object_instance\":9101,\"property_id\":\"present-value\"}'" 2>/dev/null || echo '{}')"
  echo "$XD" >"$ART/cross_device_read.json"
  XDV="$(jq -r '.value // .present_value // empty' <<<"$XD")"
  if [[ -n "$XDV" ]] && jq -e '.ok==true' <<<"$XD" >/dev/null 2>&1; then
    ok "Pi edge read 599999 AV:9101 over BACnet: $XDV °F"
    if [[ "$B_T1" != "ERR" ]] && approx "$XDV" "$B_T1" 1.0; then
      ok "cross-device value agrees with direct read ($XDV ≈ $B_T1)"
    else
      bad "cross-device value $XDV disagrees with direct read $B_T1"
    fi
  else
    bad "Pi edge could not read 599999 weather point: $(head -c 200 <<<"$XD")"
  fi
else
  skip "cross-device read skipped (Pi edge not up)"
fi

# --- C. soak with trend sampling ------------------------------------------------
hdr "C. soak ${SOAK}s, sampling every ${SAMPLE_EVERY}s → weather_trend.csv"
# FD-leak instrumentation: BACnetClient::stop() leaks the transport UDP socket per
# operation (vendored bacnet-client lifecycle.rs never stops the Arc'd NetworkLayer).
# At ~4 sockets/min the fieldbus dies at the 1024-FD ulimit in ~4-5h — root cause of
# the 2026-07-17 frozen-fallback weather in Workbench. Quantify growth over the soak.
FB_CTR="$(docker ps --format '{{.Names}}' | grep -m1 fieldbus || true)"
fd_count() { docker exec "$FB_CTR" sh -c 'ls /proc/1/fd | wc -l' 2>/dev/null || echo 0; }
FD_START=0
[[ -n "$FB_CTR" ]] && FD_START="$(fd_count)"
echo "utc,device,temp_f,rh,app_fault,last_updated" >"$TREND"
ELAPSED=0
while (( ELAPSED < SOAK )); do
  NOW="$(date -u +%FT%TZ)"
  T1="$(rp "$BENCH_IP" "$DEV1" AV 9101 2>/dev/null || echo ERR)"
  R1="$(rp "$BENCH_IP" "$DEV1" AV 9102 2>/dev/null || echo ERR)"
  F1="$(rp "$BENCH_IP" "$DEV1" BV 9106 2>/dev/null || echo ERR)"
  S1="$(rp "$BENCH_IP" "$DEV1" CSV 9107 2>/dev/null || echo ERR)"
  echo "$NOW,$DEV1,$T1,$R1,$F1,\"$S1\"" >>"$TREND"
  if [[ "$PI_UP" == "1" ]]; then
    T2="$(rp "$PI_IP" "$DEV2" AV 9101 2>/dev/null || echo ERR)"
    R2="$(rp "$PI_IP" "$DEV2" AV 9102 2>/dev/null || echo ERR)"
    F2="$(rp "$PI_IP" "$DEV2" BV 9106 2>/dev/null || echo ERR)"
    S2="$(rp "$PI_IP" "$DEV2" CSV 9107 2>/dev/null || echo ERR)"
    echo "$NOW,$DEV2,$T2,$R2,$F2,\"$S2\"" >>"$TREND"
  fi
  PI_NOTE=""
  [[ "$PI_UP" == "1" ]] && PI_NOTE="$DEV2=${T2:-n/a}°F"
  echo "${DIM}  t+${ELAPSED}s  $DEV1=$T1°F  $PI_NOTE${RST}"
  sleep "$SAMPLE_EVERY"
  ELAPSED=$((ELAPSED + SAMPLE_EVERY))
done
ok "soak complete — $(( $(wc -l <"$TREND") - 1 )) trend samples in weather_trend.csv"

# FD leak verdict over the soak window
if [[ -n "$FB_CTR" ]]; then
  FD_END="$(fd_count)"
  FD_GROWTH=$((FD_END - FD_START))
  echo "fd_start=$FD_START fd_end=$FD_END growth=$FD_GROWTH soak_secs=$SOAK" >"$ART/fd_leak.txt"
  if (( FD_GROWTH > 20 )); then
    RATE_H="$(python3 -c "print(round($FD_GROWTH * 3600 / $SOAK))")"
    bad "FD LEAK: fieldbus fds grew $FD_START → $FD_END over ${SOAK}s (~${RATE_H}/h) — BACnetClient::stop() leaks UDP socket; service dies at 1024-fd ulimit"
  else
    ok "fieldbus fd count stable over soak ($FD_START → $FD_END)"
  fi
fi

# --- D. AFTER snapshot ----------------------------------------------------------
hdr "D. AFTER snapshot + staleness assertions"
snapshot after >/dev/null
AFTER="$ART/weather_snapshot_after.txt"
A_T1="$(extract "$AFTER" bench temp_f || true)"; A_ST1="$(extract "$AFTER" bench last_updated || true)"
A_F1="$(extract "$AFTER" bench app_fault || true)"
A_T2="$(extract "$AFTER" pi temp_f || true)";    A_ST2="$(extract "$AFTER" pi last_updated || true)"
A_F2="$(extract "$AFTER" pi app_fault || true)"

check_device_fresh() {
  # check_device_fresh <name> <dev> <t_before> <stamp_before> <t_after> <stamp_after> <fault_after>
  local name="$1" dev="$2" tb="$3" sb="$4" ta="$5" sa="$6" fa="$7"
  if [[ -z "$sa" || "$sa" == "ERR" ]]; then
    bad "$name $dev: could not read weather-last-updated after soak"
    return
  fi
  if [[ "$SOAK" -lt 600 ]]; then
    skip "$name $dev: soak ${SOAK}s < 600 — skip last-updated drift (tier C low-RAM)"
    return
  fi
  if [[ "$sa" != "$sb" ]]; then
    ok "$name $dev: weather-last-updated CHANGED over soak — server data is live"
    echo "${DIM}  before: $sb${RST}"
    echo "${DIM}  after:  $sa${RST}"
  else
    bad "$name $dev: weather-last-updated FROZEN over ${SOAK}s soak ('$sa') — mirror loop dead?"
  fi
  # fallback detection: exact 70.0/50.0 pair AND app-fault active
  if [[ "$fa" == "1" ]]; then
    bad "$name $dev: app-fault BV:9106 ACTIVE after soak — serving fallback, Open-Meteo unreachable"
  elif [[ "$ta" == "70.0" || "$ta" == "70" ]] && grep -q "fallback" <<<"$sa"; then
    bad "$name $dev: values look like frozen fallback (temp=$ta, stamp mentions fallback)"
  else
    ok "$name $dev: live values (temp_f=$ta, app-fault inactive)"
  fi
}
check_device_fresh bench "$DEV1" "$B_T1" "$B_ST1" "$A_T1" "$A_ST1" "$A_F1"
if [[ "$PI_UP" == "1" ]]; then
  check_device_fresh pi "$DEV2" "$B_T2" "$B_ST2" "$A_T2" "$A_ST2" "$A_F2"
fi

# --- E. legitimacy vs real Open-Meteo -------------------------------------------
hdr "E. legitimacy: device temps vs real Open-Meteo (±3 °F)"
LEGIT_ARGS=("Madison Wisconsin" "$A_T1")
[[ "$PI_UP" == "1" ]] && LEGIT_ARGS+=("Chicago" "$A_T2")
set +e
python3 - "${LEGIT_ARGS[@]}" <<'PY' | tee "$ART/weather_legitimacy.txt"
import json, sys, urllib.request, urllib.parse
pairs = list(zip(sys.argv[1::2], sys.argv[2::2]))
rc = 0
def geocode(city):
    # Multi-word queries ("Madison Wisconsin") return no results from the geocoding
    # API; fall back to first token + admin1 filter, mirroring the product's logic.
    for name in (city, city.split()[0]):
        q = urllib.parse.urlencode({"name": name, "count": 10, "language": "en", "format": "json"})
        geo = json.load(urllib.request.urlopen(f"https://geocoding-api.open-meteo.com/v1/search?{q}", timeout=20))
        results = geo.get("results") or []
        hint = " ".join(city.split()[1:]).lower()
        for r in results:
            if not hint or hint in r.get("admin1", "").lower():
                return r
        if results:
            return results[0]
    raise RuntimeError(f"no geocode result for {city!r}")

for city, dev_val in pairs:
    try:
        loc = geocode(city)
        q2 = urllib.parse.urlencode({
            "latitude": loc["latitude"], "longitude": loc["longitude"],
            "current": "temperature_2m", "temperature_unit": "fahrenheit"})
        fc = json.load(urllib.request.urlopen(f"https://api.open-meteo.com/v1/forecast?{q2}", timeout=20))
        real = fc["current"]["temperature_2m"]
    except Exception as e:
        print(f"{city}: host-side Open-Meteo fetch FAILED ({e}) — cannot judge legitimacy")
        rc = 1
        continue
    try:
        dv = float(dev_val)
    except ValueError:
        print(f"{city}: device value '{dev_val}' unreadable")
        rc = 1
        continue
    delta = abs(dv - real)
    verdict = "MATCH" if delta <= 3.0 else "MISMATCH"
    if verdict == "MISMATCH":
        rc = 1
    print(f"{city}: real Open-Meteo now {real}°F, device serves {dv}°F (Δ{delta:.1f}) → {verdict}")
sys.exit(rc)
PY
LEGIT_RC=${PIPESTATUS[0]}
set -e
if [[ "$LEGIT_RC" -eq 0 ]]; then
  ok "device weather matches real Open-Meteo city data within ±3 °F — data is legit, not canned"
else
  bad "device weather does NOT match real Open-Meteo city data (see weather_legitimacy.txt)"
fi

# --- F. root-cause probe if anything served fallback -----------------------------
if [[ "$A_F1" == "1" || ( "$PI_UP" == "1" && "${A_F2:-0}" == "1" ) ]]; then
  hdr "F. root-cause: container egress to Open-Meteo"
  FB_CTR="$(docker ps --format '{{.Names}}' | grep -m1 fieldbus || true)"
  if [[ -n "$FB_CTR" && "$A_F1" == "1" ]]; then
    docker exec "$FB_CTR" sh -c \
      'getent hosts geocoding-api.open-meteo.com; wget -q -T 10 -O- "https://geocoding-api.open-meteo.com/v1/search?name=Madison&count=1" | head -c 200; echo' \
      >"$ART/bench_container_egress.txt" 2>&1 || true
    echo "${DIM}$(cat "$ART/bench_container_egress.txt")${RST}"
    skip "bench container egress probe saved (bench_container_egress.txt) — attach to weather issue"
  fi
  if [[ "$PI_UP" == "1" && "${A_F2:-0}" == "1" ]]; then
    pi 'CTR=$(docker ps --format "{{.Names}}" | grep -m1 fieldbus); docker exec "$CTR" sh -c "getent hosts geocoding-api.open-meteo.com; wget -q -T 10 -O- \"https://geocoding-api.open-meteo.com/v1/search?name=Chicago&count=1\" | head -c 200; echo"' \
      >"$ART/pi_container_egress.txt" 2>&1 || true
    echo "${DIM}$(cat "$ART/pi_container_egress.txt")${RST}"
    skip "pi container egress probe saved (pi_container_egress.txt) — attach to weather issue"
  fi
fi

summary
echo "${DIM}Trend artifact: $TREND — both BACnet servers stay RUNNING for Workbench trending.${RST}"
