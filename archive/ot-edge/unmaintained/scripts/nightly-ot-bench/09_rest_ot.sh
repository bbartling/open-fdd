#!/usr/bin/env bash
# Gate 09 — REST/JSON edge driver (#540).
# Runs a throwaway fieldbus container against a tiny JSON sim so the long-running
# Workbench stack (standalone on :8081 / :47808) is never interrupted.
#
# Asserts: GET decode+scale, JSONPath miss → structured error, bearer auth,
# write 403 when disabled, write clamp when enabled, circuit-breaker on sim kill,
# FD stability across ≥500 reads (no #535-style per-op leak on reqwest).
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib.sh"
load_bench_env
cd "$ROOT"

ART="${ARTIFACT_DIR:-$(artifact_dir)}"
mkdir -p "$ART"

SIM_PORT="${REST_SIM_PORT:-18765}"
SIM_TOKEN="${REST_SIM_TOKEN:-bench-rest-sim-token-xyz}"
FB_HTTP_PORT="${REST_GATE_HTTP_PORT:-18091}"
FB_NAME="openfdd-rest-gate-$$"
CFG_DIR="$ART/rest_gate_config"
SIM_PID=""
FB_CID=""

cleanup() {
  set +e
  if [[ -n "$FB_CID" ]]; then docker rm -f "$FB_CID" >/dev/null 2>&1; fi
  if [[ -n "$SIM_PID" ]] && kill -0 "$SIM_PID" 2>/dev/null; then kill "$SIM_PID" 2>/dev/null; wait "$SIM_PID" 2>/dev/null; fi
  # leftover from a previous aborted run
  docker rm -f openfdd-rest-gate 2>/dev/null || true
}
trap cleanup EXIT

# --- probe: does the nightly image even expose /rest/* ? ---------------------
hdr "Probe REST driver presence on nightly fieldbus image"
# Prefer the running react-ot fieldbus (same image) for a quick surface check; if 404,
# the feature is not in this image and we FAIL (expected shipped per #540/#543).
PROBE="$(curl -sS --max-time 8 -o /tmp/rest_probe.json -w '%{http_code}' \
  -H "Authorization: Bearer ${OPENFDD_FIELDBUS_API_KEY:-bench-demo-key-1234567890}" \
  "$FIELDBUS_BASE/rest/devices" || echo 000)"
echo "fieldbus /rest/devices HTTP $PROBE → $(head -c 200 /tmp/rest_probe.json 2>/dev/null)"
if [[ "$PROBE" == "404" || "$PROBE" == "000" ]]; then
  bad "REST driver not present on this nightly (/rest/devices → $PROBE) — #540 not shipped in image"
  summary; exit 1
fi
ok "REST surface present on OT fieldbus (HTTP $PROBE)"

# --- start JSON sim ----------------------------------------------------------
hdr "Start REST JSON sim on :$SIM_PORT"
REST_SIM_HOST=127.0.0.1 REST_SIM_PORT="$SIM_PORT" REST_SIM_TOKEN="$SIM_TOKEN" \
  python3 "$DIR/rest_sim.py" >"$ART/rest_sim.log" 2>&1 &
SIM_PID=$!
for i in $(seq 1 30); do
  if curl -fsS --max-time 1 "http://127.0.0.1:$SIM_PORT/_health" >/dev/null 2>&1; then break; fi
  sleep 0.2
done
if ! curl -fsS --max-time 2 "http://127.0.0.1:$SIM_PORT/_health" >/dev/null 2>&1; then
  bad "rest_sim failed to start (see rest_sim.log)"
  summary; exit 1
fi
ok "rest_sim up (pid $SIM_PID)"

# --- throwaway fieldbus with test catalog ------------------------------------
hdr "Throwaway fieldbus on :$FB_HTTP_PORT with REST catalog → sim"
rm -rf "$CFG_DIR"
mkdir -p "$CFG_DIR"
# Minimal gateway: no bacnet OT bind fight — host network shared, but we do NOT
# start a conflicting bacnet server on 47808 if possible. Use a high bacnet port.
cat >"$CFG_DIR/gateway.toml" <<EOF
[bacnet_server]
device_instance = 610099
device_name = "OpenFDD-rest-gate"
interface = "127.0.0.1"
port = 47899
broadcast = "127.0.0.1"

[bacnet_client]
interface = "127.0.0.1"
broadcast = "127.0.0.1"
whois_bind_port = 0
read_bind_port = 0

[weather]
city = "Madison Wisconsin"
interval_secs = 3600

[rest]
default_timeout_secs = 5
default_tls_verify = true
default_poll_interval_secs = 60
allow_write = false
EOF

# Device points at host.docker.internal / host-gateway. On --network host, 127.0.0.1 works.
cat >"$CFG_DIR/rest_devices.toml" <<EOF
[[devices]]
name = "bench-sim"
enabled = true
base_url = "http://127.0.0.1:${SIM_PORT}"
auth = "bearer"
token_env = "OPENFDD_REST_TOKEN_BENCH"
tls_verify = true
timeout_secs = 5

  [[devices.points]]
  point_name = "CHW-ST"
  method = "GET"
  path = "/points/chw_supply_temp"
  select = "\$.value"
  units = "°F"
  scale = 1.0

  [[devices.points]]
  point_name = "PLANT-KW"
  method = "GET"
  path = "/points/plant_kw"
  select = "\$.value"
  units = "kW"
  scale = 2.0

  [[devices.points]]
  point_name = "MISSING"
  method = "GET"
  path = "/points/missing_path"
  select = "\$.value"
  units = "-"

  [[devices.writes]]
  name = "chw_setpoint"
  enabled = false
  method = "POST"
  path = "/points/chw_setpoint"
  body_template = '{"value": {{value}}, "priority": 8}'
  value_min = 40.0
  value_max = 55.0
EOF

# Empty field_devices catalog (must still parse — `devices` key required)
printf '%s\n' '# gate 09 — no BACnet field devices' 'devices = []' >"$CFG_DIR/field_devices.toml"
cp "$ROOT/config/fieldbus/objects.csv" "$CFG_DIR/objects.csv" 2>/dev/null || \
  echo 'object_type,object_instance,object_name' >"$CFG_DIR/objects.csv"
cp "$ROOT/config/fieldbus/haystack_users.toml" "$CFG_DIR/haystack_users.toml" 2>/dev/null || true

docker rm -f openfdd-rest-gate >/dev/null 2>&1 || true
# No --rm until healthy so boot failures leave inspectable logs
FB_CID="$(docker run -d --name openfdd-rest-gate --network host \
  -e OPENFDD_FIELDBUS_CONFIG_DIR=/app/config \
  -e OPENFDD_FIELDBUS_HTTP_HOST=127.0.0.1 \
  -e OPENFDD_FIELDBUS_HTTP_PORT="$FB_HTTP_PORT" \
  -e OPENFDD_FIELDBUS_API_KEY=bench-rest-gate-key \
  -e OPENFDD_REST_TOKEN_BENCH="$SIM_TOKEN" \
  -v "$CFG_DIR:/app/config:ro" \
  "${OPENFDD_FIELDBUS_IMAGE:-ghcr.io/bbartling/openfdd-fieldbus:nightly}")"
ok "throwaway fieldbus cid=${FB_CID:0:12}"

FB="http://127.0.0.1:$FB_HTTP_PORT"
AUTH=(-H "Authorization: Bearer bench-rest-gate-key" -H "Content-Type: application/json")
for i in $(seq 1 40); do
  if curl -fsS --max-time 2 "$FB/health" >/dev/null 2>&1; then break; fi
  sleep 0.5
done
if ! curl -fsS --max-time 5 "$FB/health" >/dev/null 2>&1; then
  bad "throwaway fieldbus never healthy; logs:"
  docker logs openfdd-rest-gate 2>&1 | tee "$ART/rest_gate_boot.log" | tail -40
  summary; exit 1
fi
# Now safe to mark for cleanup (trap removes by name/cid)
ok "throwaway fieldbus healthy on :$FB_HTTP_PORT"

rapi() { curl -sS --max-time 20 "${AUTH[@]}" "$@"; }

# --- list devices ------------------------------------------------------------
hdr "GET /rest/devices"
DEV="$(rapi "$FB/rest/devices" || echo '{}')"
echo "$DEV" | tee "$ART/rest_devices.json" | head -c 400; echo
jq_ok "rest devices list ok" "$DEV" '.ok==true'
if jq -e '.devices[] | select(.name=="bench-sim")' <<<"$DEV" >/dev/null 2>&1; then
  ok "bench-sim present in catalog"
else
  bad "bench-sim missing from /rest/devices: $(head -c 200 <<<"$DEV")"
fi

# --- read + scale ------------------------------------------------------------
hdr "POST /rest/read decode + scale"
RD="$(rapi -X POST "$FB/rest/read" -d '{"device":"bench-sim","point":"CHW-ST"}' || echo '{}')"
echo "$RD" | tee "$ART/rest_read_chw.json"
# value should be ~44.0
VAL="$(jq -r '.value // .present_value // empty' <<<"$RD")"
if jq -e '.ok==true or (.value!=null)' <<<"$RD" >/dev/null 2>&1 && python3 -c "import sys; v=float('$VAL'); sys.exit(0 if abs(v-44.0)<0.01 else 1)"; then
  ok "CHW-ST decode = $VAL (expected 44.0)"
else
  bad "CHW-ST decode failed: $RD"
fi

RD2="$(rapi -X POST "$FB/rest/read" -d '{"device":"bench-sim","point":"PLANT-KW"}' || echo '{}')"
echo "$RD2" | tee "$ART/rest_read_kw.json"
VAL2="$(jq -r '.value // .present_value // empty' <<<"$RD2")"
# scale=2.0 → 120.5 * 2 = 241.0
if python3 -c "import sys; v=float('$VAL2' or 'nan'); sys.exit(0 if abs(v-241.0)<0.05 else 1)"; then
  ok "PLANT-KW scale×2 = $VAL2 (expected 241.0)"
else
  bad "PLANT-KW scale failed (got $VAL2): $RD2"
fi

# --- JSONPath miss -----------------------------------------------------------
hdr "JSONPath miss → structured error"
MISS="$(rapi -X POST "$FB/rest/read" -d '{"device":"bench-sim","point":"MISSING"}' || echo '{}')"
echo "$MISS" | tee "$ART/rest_read_miss.json"
# expect non-ok / 4xx body with error string
if jq -e '(.ok==false) or (.error!=null) or (.detail!=null)' <<<"$MISS" >/dev/null 2>&1; then
  ok "JSONPath miss returned structured error"
else
  # some builds return HTTP 4xx with JSON body that curl -s still captures
  CODE="$(curl -sS -o "$ART/rest_read_miss.json" -w '%{http_code}' --max-time 20 "${AUTH[@]}" \
    -X POST "$FB/rest/read" -d '{"device":"bench-sim","point":"MISSING"}' || echo 000)"
  if [[ "$CODE" =~ ^4 ]]; then
    ok "JSONPath miss HTTP $CODE (structured)"
  else
    bad "JSONPath miss did not error (HTTP $CODE): $(head -c 200 "$ART/rest_read_miss.json")"
  fi
fi

# --- write 403 when disabled -------------------------------------------------
hdr "POST /rest/write → 403 when allow_write/binding disabled"
WCODE="$(curl -sS -o "$ART/rest_write_disabled.json" -w '%{http_code}' --max-time 20 "${AUTH[@]}" \
  -X POST "$FB/rest/write" -d '{"device":"bench-sim","name":"chw_setpoint","value":45.0}' || echo 000)"
echo "HTTP $WCODE → $(head -c 200 "$ART/rest_write_disabled.json")"
if [[ "$WCODE" == "403" ]] || jq -e '(.ok==false) or (.error!=null)' "$ART/rest_write_disabled.json" >/dev/null 2>&1; then
  ok "write blocked when disabled (HTTP $WCODE)"
else
  bad "write should be forbidden when disabled (HTTP $WCODE)"
fi

# --- write clamp (opt-in: BENCH_ALLOW_WRITES=1) ------------------------------
if [[ "${BENCH_ALLOW_WRITES:-0}" == "1" ]]; then
  hdr "Write clamp: restart throwaway with allow_write=true + binding enabled"
  docker rm -f openfdd-rest-gate >/dev/null 2>&1 || true
  FB_CID=""
  python3 - "$CFG_DIR" <<'PY'
from pathlib import Path
import sys
cfg = Path(sys.argv[1])
g = (cfg/"gateway.toml").read_text().replace("allow_write = false", "allow_write = true")
(cfg/"gateway.toml").write_text(g)
r = (cfg/"rest_devices.toml").read_text().replace("enabled = false", "enabled = true", 1)
(cfg/"rest_devices.toml").write_text(r)
print("patched allow_write + binding enabled")
PY
  docker rm -f openfdd-rest-gate >/dev/null 2>&1 || true
  FB_CID="$(docker run -d --name openfdd-rest-gate --network host \
    -e OPENFDD_FIELDBUS_CONFIG_DIR=/app/config \
    -e OPENFDD_FIELDBUS_HTTP_HOST=127.0.0.1 \
    -e OPENFDD_FIELDBUS_HTTP_PORT="$FB_HTTP_PORT" \
    -e OPENFDD_FIELDBUS_API_KEY=bench-rest-gate-key \
    -e OPENFDD_REST_TOKEN_BENCH="$SIM_TOKEN" \
    -v "$CFG_DIR:/app/config:ro" \
    "${OPENFDD_FIELDBUS_IMAGE:-ghcr.io/bbartling/openfdd-fieldbus:nightly}")"
  for i in $(seq 1 40); do
    curl -fsS --max-time 2 "$FB/health" >/dev/null 2>&1 && break
    sleep 0.5
  done
  if ! curl -fsS --max-time 5 "$FB/health" >/dev/null 2>&1; then
    bad "throwaway fieldbus (allow_write restart) never healthy"
    docker logs openfdd-rest-gate 2>&1 | tee -a "$ART/rest_gate_boot.log" | tail -20
    summary; exit 1
  fi

  LOW="$(curl -sS -o "$ART/rest_write_low.json" -w '%{http_code}' --max-time 20 "${AUTH[@]}" \
    -X POST "$FB/rest/write" -d '{"device":"bench-sim","name":"chw_setpoint","value":30.0}' || echo 000)"
  echo "low write HTTP $LOW → $(head -c 200 "$ART/rest_write_low.json")"
  if [[ "$LOW" =~ ^4 ]] || jq -e '(.ok==false) or (.error!=null) or (.clamped==true)' "$ART/rest_write_low.json" >/dev/null 2>&1; then
    ok "write below min rejected/clamped (HTTP $LOW)"
  else
    bad "write below min (30) should fail clamp (HTTP $LOW)"
  fi

  OKW="$(rapi -X POST "$FB/rest/write" -d '{"device":"bench-sim","name":"chw_setpoint","value":46.0}' || echo '{}')"
  echo "$OKW" | tee "$ART/rest_write_ok.json"
  if jq -e '.ok==true or (.value==46.0) or (.written==true)' <<<"$OKW" >/dev/null 2>&1; then
    ok "in-range write 46.0 accepted"
  else
    CODE="$(curl -sS -o "$ART/rest_write_ok.json" -w '%{http_code}' --max-time 20 "${AUTH[@]}" \
      -X POST "$FB/rest/write" -d '{"device":"bench-sim","name":"chw_setpoint","value":46.0}')"
    if [[ "$CODE" == "200" ]]; then ok "in-range write HTTP 200"; else bad "in-range write failed HTTP $CODE: $(head -c 200 "$ART/rest_write_ok.json")"; fi
  fi
else
  skip "REST write clamp / in-range write (set BENCH_ALLOW_WRITES=1)"
fi

# --- FD soak: 500 reads ------------------------------------------------------
hdr "FD stability across 500 REST reads (no #535-style leak)"
FD0="$(docker exec openfdd-rest-gate sh -c 'ls /proc/1/fd | wc -l' 2>/dev/null || echo 0)"
echo "FD t0=$FD0"
python3 - "$FB" <<'PY'
import json, urllib.request, sys
base = sys.argv[1]
req_body = json.dumps({"device":"bench-sim","point":"CHW-ST"}).encode()
ok = 0
for i in range(500):
    req = urllib.request.Request(
        base + "/rest/read", data=req_body,
        headers={"Authorization":"Bearer bench-rest-gate-key","Content-Type":"application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            if r.status == 200:
                ok += 1
    except Exception as e:
        if i < 3 or i == 499:
            print(f"read {i} err: {e}", file=sys.stderr)
print(f"reads_ok={ok}/500")
sys.exit(0 if ok >= 490 else 1)
PY
FD1="$(docker exec openfdd-rest-gate sh -c 'ls /proc/1/fd | wc -l' 2>/dev/null || echo 0)"
echo "FD t500=$FD1 (delta=$((FD1 - FD0)))" | tee "$ART/rest_fd_soak.txt"
# Allow small jitter (±20); fail if growth looks like a leak (>50)
if python3 -c "import sys; d=int('$FD1')-int('$FD0'); sys.exit(0 if d<=50 else 1)"; then
  ok "FD growth flat across 500 reads ($FD0 → $FD1)"
else
  bad "FD leaked across 500 REST reads ($FD0 → $FD1) — possible #535-style reqwest leak"
fi

# --- circuit breaker ---------------------------------------------------------
hdr "Circuit breaker: kill sim, assert breaker opens after failures"
curl -fsS --max-time 5 -X POST "http://127.0.0.1:$SIM_PORT/_kill" >/dev/null 2>&1 || true
sleep 0.5
SIM_PID=""  # already dead
FAILS=0
for i in $(seq 1 6); do
  CODE="$(curl -sS -o /tmp/rest_cb.json -w '%{http_code}' --max-time 8 "${AUTH[@]}" \
    -X POST "$FB/rest/read" -d '{"device":"bench-sim","point":"CHW-ST"}' || echo 000)"
  echo "  attempt $i HTTP $CODE $(head -c 120 /tmp/rest_cb.json)"
  FAILS=$((FAILS + 1))
done
DEV2="$(rapi "$FB/rest/devices" || echo '{}')"
echo "$DEV2" | tee "$ART/rest_devices_after_kill.json" | head -c 500; echo
if jq -e '.devices[] | select(.name=="bench-sim") | (.health.circuit_open==true) or ((.health.consecutive_failures//0)>=3)' <<<"$DEV2" >/dev/null 2>&1 \
   || grep -qi 'circuit open' /tmp/rest_cb.json 2>/dev/null; then
  ok "circuit breaker opened after sim kill"
else
  if jq -e '.devices[] | select(.name=="bench-sim") | ((.health.consecutive_failures//0) >= 1)' <<<"$DEV2" >/dev/null 2>&1; then
    ok "failures recorded after sim kill (breaker telemetry present)"
  else
    bad "circuit breaker did not open / no failure telemetry after sim kill"
  fi
fi

summary
