#!/usr/bin/env bash
# Open-FDD / VOLTTRON-style platform driver — polls the field-bus sidecar via /api/*.
#
# Mimics how Open-FDD (or a VOLTTRON platform driver) would interact with the sidecar:
# heartbeat, catalog load, point reads, poll engine scrape, hosted-server inventory,
# weather, and Haystack — all through the /api prefix Open-FDD uses in production.
#
# Critical bench assertion: device 5007 analog-output:2466 priority 8 == 55% override.
#
# Usage:
#   OPENFDD_FIELDBUS_API_KEY=... scripts/openfdd_platform_driver.sh
#   DRIVER_CYCLES=5 DRIVER_INTERVAL_SECS=30 scripts/openfdd_platform_driver.sh
set -uo pipefail

BASE="${DRIVER_BASE:-${SMOKE_BASE:-http://127.0.0.1:8080}}"
KEY="${OPENFDD_FIELDBUS_API_KEY:-${RUSTY_GATEWAY_API_KEY:-}}"
CYCLES="${DRIVER_CYCLES:-3}"
INTERVAL="${DRIVER_INTERVAL_SECS:-30}"
TIMEOUT="${DRIVER_TIMEOUT:-45}"
SUP_TIMEOUT="${DRIVER_SUP_TIMEOUT:-240}"

DEV="${DRIVER_DEVICE:-5007}"
OVR_TYPE="${DRIVER_OVERRIDE_TYPE:-analog-output}"
OVR_INST="${DRIVER_OVERRIDE_INST:-2466}"
EXPECT_PRIORITY="${DRIVER_OVERRIDE_PRIORITY:-8}"
EXPECT_VALUE="${DRIVER_OVERRIDE_VALUE:-55}"
HIS_POINT="${DRIVER_HAYSTACK_POINT:-demo-vav-1-01-zat}"

command -v jq >/dev/null || { echo "FATAL: jq required" >&2; exit 2; }

AUTH=()
[[ -n "$KEY" ]] && AUTH=(-H "Authorization: Bearer $KEY")

PASS=0
FAIL=0
GREEN=$'\033[32m'; RED=$'\033[31m'; YEL=$'\033[33m'; DIM=$'\033[2m'; BOLD=$'\033[1m'; RST=$'\033[0m'

api()  { curl -fsS --max-time "$TIMEOUT" -H 'Content-Type: application/json' "${AUTH[@]}" "$@"; }
apis() { curl -fsS --max-time "$SUP_TIMEOUT" -H 'Content-Type: application/json' "${AUTH[@]}" "$@"; }

ok()  { PASS=$((PASS+1)); echo "  ${GREEN}ok${RST} $*"; }
bad() { FAIL=$((FAIL+1)); echo "  ${RED}FAIL${RST} $*" >&2; }
note() { echo "  ${DIM}$*${RST}"; }

approx() { awk -v a="$1" -v b="$2" 'BEGIN{d=a-b; if(d<0)d=-d; exit !(d<=1.0)}'; }

check_json() {
  local label="$1" json="$2"; shift 2
  if jq -e "$@" >/dev/null 2>&1 <<<"$json"; then ok "$label"; else bad "$label"; note "$(jq -c . <<<"$json" 2>/dev/null | head -c 300)"; fi
}

echo "${BOLD}Open-FDD platform driver (API /api/* poll cycles)${RST}"
echo "base=$BASE device=$DEV cycles=$CYCLES interval=${INTERVAL}s"
[[ -z "$KEY" ]] && echo "${YEL}(no API key — auth disabled)${RST}"

for ((cycle=1; cycle<=CYCLES; cycle++)); do
  echo
  echo "${BOLD}--- driver cycle $cycle/$CYCLES ($(date -u +%H:%M:%SZ)) ---${RST}"

  # 1) Heartbeat — Open-FDD checks sidecar liveness before scheduling work
  if H=$(api "$BASE/api/health"); then
    check_json "GET /api/health" "$H" '.ok==true and .service=="openfdd-fieldbus"'
    note "poll_running=$(jq -r .poll_running <<<"$H") server=$(jq -r .bacnet_server_instance <<<"$H")"
  else bad "GET /api/health unreachable"; fi

  # 2) Who-Is device discovery (Open-FDD entry point)
  if W=$(api -X POST "$BASE/api/bacnet/whois" -d '{}'); then
    check_json "POST /api/bacnet/whois" "$W" '.devices|length>0'
    note "devices=$(jq -c '[.devices[].device_instance]' <<<"$W")"
  else bad "POST /api/bacnet/whois"; fi

  # 3) Poll engine — trigger scrape + consume cached values (background poll targets)
  if PO=$(apis -X POST "$BASE/api/bacnet/poll/once"); then
    check_json "POST /api/bacnet/poll/once" "$PO" '.points_polled>0'
    note "polled=$(jq -r .points_polled <<<"$PO") errored=$(jq -r .points_errored <<<"$PO")"
  else bad "POST /api/bacnet/poll/once"; fi

  if PS=$(api "$BASE/api/bacnet/poll/status"); then
    check_json "GET /api/bacnet/poll/status" "$PS" '.points_tracked>0'
    note "tracked=$(jq -r .points_tracked <<<"$PS") last_cycle=$(jq -r .last_cycle_ts <<<"$PS")"
  else bad "GET /api/bacnet/poll/status"; fi

  # 4) Hosted server inventory (Open-FDD reads weather/diagnostic AVs from sidecar server)
  if SP=$(api "$BASE/api/bacnet/server/points"); then
    check_json "GET /api/bacnet/server/points" "$SP" '.ok==true and (.objects|length)>0'
    check_json "hosted outside-air-temperature AV:9101" "$SP" 'any(.objects[]; .name=="outside-air-temperature" and .instance==9101)'
  else bad "GET /api/bacnet/server/points"; fi

  # 5) Weather mirror (Open-FDD consumes JSON, sidecar mirrors to BACnet AVs)
  if WX=$(api "$BASE/api/weather"); then
    check_json "GET /api/weather temp_f present" "$WX" '.temp_f != null'
  else bad "GET /api/weather"; fi

  # 6) Haystack read-only scrape
  if HR=$(api -X POST "$BASE/api/haystack/read" -d '{"filter":"point and temp"}'); then
    check_json "POST /api/haystack/read" "$HR" '.ok==true'
  else bad "POST /api/haystack/read"; fi

  # 7) BACnet discovery + override audit (every cycle on bench device 5007)
  if PD=$(apis -X POST "$BASE/api/bacnet/point-discovery" -d "{\"device_instance\":$DEV}"); then
    check_json "POST /api/bacnet/point-discovery finds AO:2466" "$PD" \
      --arg oi "$OVR_TYPE,$OVR_INST" 'any(.objects[]; .object_identifier==$oi and .commandable==true)'
  else bad "POST /api/bacnet/point-discovery"; fi

  if PA=$(api -X POST "$BASE/api/bacnet/priority-array" -d "{\"device_instance\":$DEV,\"object_type\":\"$OVR_TYPE\",\"object_instance\":$OVR_INST}"); then
    PV=$(jq -r --argjson p "$EXPECT_PRIORITY" '.priority_array[] | select(.priority_level==$p) | .value // empty' <<<"$PA")
    if [[ -n "$PV" && "$PV" != "null" ]] && approx "$PV" "$EXPECT_VALUE"; then
      ok "P${EXPECT_PRIORITY} override on $OVR_TYPE:$OVR_INST = ${PV} (~${EXPECT_VALUE}%)"
    else
      bad "P${EXPECT_PRIORITY} override on $OVR_TYPE:$OVR_INST = '${PV}' (expected ~${EXPECT_VALUE})"
    fi
  else bad "POST /api/bacnet/priority-array"; fi

  # 8) Write approval dry-run only (Open-FDD supervised write gate — no bus I/O)
  if DR=$(api -X POST "$BASE/api/bacnet/write-dry-run" \
    -d "{\"device_instance\":$DEV,\"object_type\":\"$OVR_TYPE\",\"object_instance\":$OVR_INST,\"value\":null,\"priority\":10}"); then
    check_json "POST /api/bacnet/write-dry-run" "$DR" '.dry_run==true'
  else bad "POST /api/bacnet/write-dry-run"; fi

  if (( cycle < CYCLES )); then
    note "sleep ${INTERVAL}s before next cycle..."
    sleep "$INTERVAL"
  fi
done

echo
echo "${BOLD}Driver summary: ${GREEN}${PASS} passed${RST}, ${RED}${FAIL} failed${RST} (${CYCLES} cycles)${RST}"
[[ "$FAIL" -eq 0 ]] || { echo "${RED}PLATFORM DRIVER FAILED${RST}" >&2; exit 1; }
echo "${GREEN}PLATFORM DRIVER PASSED${RST}"
