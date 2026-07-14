#!/usr/bin/env bash
# Open-FDD field-bus sidecar smoke test.
#
# Mirrors the Open-FDD nightly bench validation for BACnet: exercises the full
# client feature set through the REST API and asserts the live test-bench state.
#
# Coverage: health, /api/health, Who-Is discover, ReadProperty, RPM, point
# discovery, priority-array, supervisory override audit, WriteProperty (safe
# low-priority) + Null release, write-dry-run, poll engine, hosted server
# objects, and weather.
#
# Key validation (super important): device 5007 analogOutput:2466 ("ACTUATOR-0")
# carries an operator override of 55% at priority 8. The priority-array and
# supervisory checks must surface priority_level 8 == 55.
#
# Usage:
#   SMOKE_BASE=http://127.0.0.1:8080 OPENFDD_FIELDBUS_API_KEY=... scripts/smoke_test.sh
set -uo pipefail

BASE="${SMOKE_BASE:-http://127.0.0.1:8080}"
# Matches openapi_bench::DEFAULT_BENCH_API_KEY and .env.example (override for production).
KEY="${OPENFDD_FIELDBUS_API_KEY:-${RUSTY_GATEWAY_API_KEY:-bench-demo-key-1234567890}}"
TIMEOUT="${SMOKE_TIMEOUT:-45}"

DEV="${SMOKE_DEVICE:-5007}"
READ_TYPE="${SMOKE_READ_TYPE:-analog-input}"
READ_INST="${SMOKE_READ_INST:-1173}"
OVR_TYPE="${SMOKE_OVERRIDE_TYPE:-analog-output}"
OVR_INST="${SMOKE_OVERRIDE_INST:-2466}"
EXPECT_PRIORITY="${SMOKE_OVERRIDE_PRIORITY:-8}"
EXPECT_VALUE="${SMOKE_OVERRIDE_VALUE:-55}"
WRITE_PRIORITY="${SMOKE_WRITE_PRIORITY:-10}"   # below the P8 operator override, so PV stays 55
HOSTED_INSTANCE="${SMOKE_HOSTED_INSTANCE:-599999}"
# Point discovery + supervisory audit walk the whole object-list through the
# MSTP router, so they need a much longer budget than a single read.
SUP_TIMEOUT="${SMOKE_SUP_TIMEOUT:-240}"

command -v jq >/dev/null || { echo "FATAL: jq is required" >&2; exit 2; }

AUTH=()
[[ -n "$KEY" ]] && AUTH=(-H "Authorization: Bearer $KEY")

PASS=0
FAIL=0
GREEN=$'\033[32m'; RED=$'\033[31m'; DIM=$'\033[2m'; BOLD=$'\033[1m'; RST=$'\033[0m'

api()  { curl -fsS --max-time "$TIMEOUT" -H 'Content-Type: application/json' "${AUTH[@]}" "$@"; }
apis() { curl -fsS --max-time "$SUP_TIMEOUT" -H 'Content-Type: application/json' "${AUTH[@]}" "$@"; }

ok()   { PASS=$((PASS+1)); echo "${GREEN}PASS${RST} $*"; }
bad()  { FAIL=$((FAIL+1)); echo "${RED}FAIL${RST} $*" >&2; }
hdr()  { echo; echo "${BOLD}== $* ==${RST}"; }

# jq_ok <label> <json> [jq args...] <filter>  — pass if the jq filter is truthy
jq_ok() {
  local label="$1" json="$2"; shift 2
  if jq -e "$@" >/dev/null 2>&1 <<<"$json"; then
    ok "$label"
  else
    bad "$label"
    echo "${DIM}$(jq -c . <<<"$json" 2>/dev/null | head -c 400)${RST}" >&2
  fi
}

# numeric approx equality within +/-1.0
approx() { awk -v a="$1" -v b="$2" 'BEGIN{d=a-b; if(d<0)d=-d; exit !(d<=1.0)}'; }

echo "${BOLD}Open-FDD field-bus sidecar smoke test${RST}"
echo "base=$BASE device=$DEV override=${OVR_TYPE}:${OVR_INST} expect P${EXPECT_PRIORITY}=${EXPECT_VALUE}"
[[ -z "$KEY" ]] && echo "${DIM}(no API key set — assuming auth disabled)${RST}"

# ---- liveness --------------------------------------------------------------
hdr "Liveness"
if H=$(api "$BASE/health"); then jq_ok "GET /health" "$H" '.ok==true'; else bad "GET /health unreachable"; fi
if H=$(api "$BASE/api/health"); then
  jq_ok "GET /api/health (Open-FDD shape)" "$H" '.ok==true'
  echo "${DIM}  service=$(jq -r .service <<<"$H") git_sha=$(jq -r .git_sha <<<"$H")${RST}"
else bad "GET /api/health unreachable"; fi

# ---- Who-Is discover (Open-FDD entry point) --------------------------------
hdr "Who-Is discover"
if W=$(api -X POST "$BASE/bacnet/whois" -d '{}'); then
  jq_ok "Who-Is finds device $DEV" "$W" --arg d "$DEV" 'any(.devices[]; (.device_instance|tostring)==$d)'
  echo "${DIM}  devices=$(jq -c '[.devices[].device_instance]' <<<"$W")${RST}"
else bad "POST /bacnet/whois"; fi

# ---- Who-Is router (MS/TP routed device 5007 via 192.168.204.200) ---------
hdr "Who-Is router-to-network"
if WR=$(api -X POST "$BASE/bacnet/whois-router" -d '{}'); then
  jq_ok "whois-router finds network 2000" "$WR" 'any(.routers[]; (.networks[]|tonumber)==2000)'
  echo "${DIM}  routers=$(jq -c '.routers' <<<"$WR")${RST}"
else bad "POST /bacnet/whois-router"; fi

# ---- ReadProperty ----------------------------------------------------------
hdr "ReadProperty"
if R=$(api -X POST "$BASE/bacnet/read" -d "{\"device_instance\":$DEV,\"object_type\":\"$READ_TYPE\",\"object_instance\":$READ_INST}"); then
  jq_ok "read $READ_TYPE:$READ_INST present-value" "$R" '.value != null'
  echo "${DIM}  value=$(jq -r .value <<<"$R") tag=$(jq -r .tag <<<"$R")${RST}"
else bad "POST /bacnet/read"; fi

# ---- RPM -------------------------------------------------------------------
hdr "ReadPropertyMultiple"
RPM_BODY="{\"device_instance\":$DEV,\"objects\":[{\"object_type\":\"$READ_TYPE\",\"object_instance\":$READ_INST,\"properties\":[{\"property_id\":\"present-value\"}]}]}"
if M=$(api -X POST "$BASE/bacnet/rpm" -d "$RPM_BODY"); then
  jq_ok "RPM returns results" "$M" '(.results|length)>0'
else bad "POST /bacnet/rpm"; fi

# ---- point discovery -------------------------------------------------------
hdr "Point discovery"
if D=$(apis -X POST "$BASE/api/bacnet/point-discovery" -d "{\"device_instance\":$DEV}"); then
  jq_ok "discovery finds $OVR_TYPE,$OVR_INST" "$D" --arg oi "$OVR_TYPE,$OVR_INST" 'any(.objects[]; .object_identifier==$oi)'
  jq_ok "$OVR_TYPE,$OVR_INST is commandable" "$D" --arg oi "$OVR_TYPE,$OVR_INST" 'any(.objects[]; .object_identifier==$oi and .commandable==true)'
  jq_ok "$OVR_TYPE,$OVR_INST has a real object name (not ERROR - Missing Data)" "$D" --arg oi "$OVR_TYPE,$OVR_INST" \
    'any(.objects[]; .object_identifier==$oi and .name != "ERROR - Missing Data" and .name != "?")'
  echo "${DIM}  objects=$(jq -r '.objects|length' <<<"$D")${RST}"
else bad "POST /api/bacnet/point-discovery"; fi

# ---- priority-array (CRITICAL override validation) -------------------------
hdr "Priority array (P${EXPECT_PRIORITY} override)"
if PA=$(api -X POST "$BASE/bacnet/priority-array" -d "{\"device_instance\":$DEV,\"object_type\":\"$OVR_TYPE\",\"object_instance\":$OVR_INST}"); then
  echo "${DIM}$(jq -c '.priority_array' <<<"$PA")${RST}"
  PV=$(jq -r --argjson p "$EXPECT_PRIORITY" '.priority_array[] | select(.priority_level==$p) | .value // empty' <<<"$PA")
  if [[ -n "$PV" && "$PV" != "null" ]] && approx "$PV" "$EXPECT_VALUE"; then
    ok "priority ${EXPECT_PRIORITY} = ${PV} (expected ~${EXPECT_VALUE}) — operator override confirmed"
  else
    bad "priority ${EXPECT_PRIORITY} = '${PV}' (expected ~${EXPECT_VALUE})"
  fi
else bad "POST /bacnet/priority-array"; fi

# ---- supervisory override audit --------------------------------------------
hdr "Supervisory override audit"
if S=$(apis -X POST "$BASE/api/bacnet/supervisory" -d "{\"device_instance\":$DEV}"); then
  echo "${DIM}  overrides=$(jq -c '.points_with_overrides' <<<"$S")${RST}"
  jq_ok "supervisory audit reports P${EXPECT_PRIORITY} override on $OVR_TYPE,$OVR_INST" "$S" \
    --arg oi "$OVR_TYPE,$OVR_INST" --argjson p "$EXPECT_PRIORITY" \
    'any(.points_with_overrides[]; .object_identifier==$oi and (.override_priority_levels|index($p)))'
  jq_ok "override value at P${EXPECT_PRIORITY} is ~${EXPECT_VALUE}" "$S" \
    --arg oi "$OVR_TYPE,$OVR_INST" --argjson p "$EXPECT_PRIORITY" --argjson v "$EXPECT_VALUE" \
    'any(.points_with_overrides[] | select(.object_identifier==$oi) | .overrides[]; .priority_level==$p and ((.value-$v)|if .<0 then -. else . end)<=1)'
else bad "POST /bacnet/supervisory"; fi

# ---- WriteProperty (safe, low priority) + Null release ---------------------
hdr "WriteProperty + Null release (safe P${WRITE_PRIORITY})"
WBODY="{\"device_instance\":$DEV,\"object_type\":\"$OVR_TYPE\",\"object_instance\":$OVR_INST,\"value\":42.0,\"priority\":$WRITE_PRIORITY}"
if WR=$(api -X POST "$BASE/bacnet/write" -d "$WBODY"); then
  jq_ok "write 42.0 @ P${WRITE_PRIORITY}" "$WR" '.status=="success"'
else bad "POST /bacnet/write"; fi
RELBODY="{\"device_instance\":$DEV,\"object_type\":\"$OVR_TYPE\",\"object_instance\":$OVR_INST,\"value\":null,\"priority\":$WRITE_PRIORITY}"
if RL=$(api -X POST "$BASE/bacnet/write" -d "$RELBODY"); then
  jq_ok "release null @ P${WRITE_PRIORITY}" "$RL" '.released==true'
else bad "POST /bacnet/write (release)"; fi
# Confirm the P8 operator override survived our P10 write/release.
if PA2=$(api -X POST "$BASE/bacnet/priority-array" -d "{\"device_instance\":$DEV,\"object_type\":\"$OVR_TYPE\",\"object_instance\":$OVR_INST}"); then
  PV2=$(jq -r --argjson p "$EXPECT_PRIORITY" '.priority_array[] | select(.priority_level==$p) | .value // empty' <<<"$PA2")
  if [[ -n "$PV2" ]] && approx "$PV2" "$EXPECT_VALUE"; then ok "P${EXPECT_PRIORITY} override intact after write/release (${PV2})"; else bad "P${EXPECT_PRIORITY} override changed to '${PV2}'"; fi
fi

# ---- write-dry-run ---------------------------------------------------------
hdr "Write dry-run (no bus I/O)"
if DR=$(api -X POST "$BASE/bacnet/write-dry-run" -d "{\"device_instance\":$DEV,\"object_type\":\"$OVR_TYPE\",\"object_instance\":$OVR_INST,\"value\":null,\"priority\":$WRITE_PRIORITY}"); then
  jq_ok "dry-run validates null release" "$DR" '.dry_run==true and .released==true'
else bad "POST /bacnet/write-dry-run"; fi

# ---- hosted server objects -------------------------------------------------
hdr "Hosted server (device $HOSTED_INSTANCE)"
if O=$(api "$BASE/bacnet/server/objects"); then
  jq_ok "weather point outside-air-temperature @ AV:9101" "$O" 'any(.objects[]; .name=="outside-air-temperature" and .instance==9101)'
  jq_ok "weather-last-updated @ CSV:9107" "$O" 'any(.objects[]; .name=="weather-last-updated" and .instance==9107)'
  jq_ok "weather point has Open-Meteo description" "$O" 'any(.objects[]; .name=="outside-air-temperature" and (.description|test("Open-Meteo")))'
  jq_ok "openfdd-optimization-enabled is commandable" "$O" 'any(.objects[]; .name=="openfdd-optimization-enabled" and .commandable==true and .api_writable==false)'
else bad "GET /bacnet/server/objects"; fi

if C=$(api "$BASE/bacnet/server/commandable"); then
  jq_ok "commandable list includes BV:9010" "$C" 'any(.objects[]; .name=="openfdd-optimization-enabled" and .instance==9010)'
else bad "GET /bacnet/server/commandable"; fi

if U=$(api -X POST "$BASE/bacnet/server/update" -d '{"updates":{"openfdd-optimization-enabled":true}}'); then
  jq_ok "REST rejects write to commandable BV:9010" "$U" '.result["openfdd-optimization-enabled"]|test("rejected")'
else bad "POST /bacnet/server/update (commandable reject)"; fi

if U2=$(api -X POST "$BASE/bacnet/server/update" -d '{"updates":{"openfdd-active-fault-count":1.0}}'); then
  jq_ok "REST allows write to server-owned AV:9003" "$U2" '.result["openfdd-active-fault-count"]=="updated"'
else bad "POST /bacnet/server/update (server-owned)"; fi

# ---- poll engine -----------------------------------------------------------
hdr "Poll engine"
if PO=$(apis -X POST "$BASE/bacnet/poll/once"); then
  jq_ok "poll/once polls configured points" "$PO" '.points_polled>0'
  echo "${DIM}  polled=$(jq -r .points_polled <<<"$PO") errored=$(jq -r .points_errored <<<"$PO")${RST}"
else bad "POST /bacnet/poll/once"; fi
if PS=$(api "$BASE/bacnet/poll/status"); then
  jq_ok "poll/status tracks last values" "$PS" '.points_tracked>0'
else bad "GET /bacnet/poll/status"; fi

# ---- weather ---------------------------------------------------------------
hdr "Weather (Open-Meteo)"
if WX=$(api "$BASE/weather"); then
  jq_ok "weather present" "$WX" '.temp_f != null'
  jq_ok "weather last_updated_label present" "$WX" '.last_updated_label != null'
  echo "${DIM}  $(jq -c '{temp_f,humidity,dewpoint_f,location,from_api,last_updated_label}' <<<"$WX")${RST}"
else bad "GET /weather"; fi

# ---- summary ---------------------------------------------------------------
echo
echo "${BOLD}Summary: ${GREEN}${PASS} passed${RST}, ${RED}${FAIL} failed${RST}"
[[ "$FAIL" -eq 0 ]] || { echo "${RED}SMOKE TEST FAILED${RST}" >&2; exit 1; }
echo "${GREEN}SMOKE TEST PASSED${RST}"
