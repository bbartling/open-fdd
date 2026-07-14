#!/usr/bin/env bash
# Open-FDD-style bench test — Rust sidecar REST driver + per-feature BACnet PCAP validation.
#
# Mirrors open-fdd/scripts/smoke_live_fdd_validation.sh (30m interval cycles) but drives
# diy-bacnet-server directly: BACnet client matrix, Modbus TCP (host in POST body),
# Haystack (gateway HAYSTACK_* env), and optional sustained soak.
#
# Usage:
#   OPENFDD_FIELDBUS_API_KEY=... scripts/bench_test.sh
#   BENCH_MINUTES=30 BENCH_INTERVAL_SECS=60 scripts/bench_test.sh   # half-hour soak
#   BENCH_PCAP=0 scripts/bench_test.sh                              # skip PCAP phases
#
# Haystack against Niagara requires sidecar started with:
#   HAYSTACK_BASE_URL=https://192.168.204.11/haystack
#   HAYSTACK_USER=open_fdd HAYSTACK_PASS=... HAYSTACK_AUTH_MODE=basic
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/fieldbus/bench_lib.sh
source "$SCRIPT_DIR/bench_lib.sh"

bench_load_env "$ROOT"
bench_require_tools
bench_auth_args

MINUTES="${BENCH_MINUTES:-0}"
INTERVAL="${BENCH_INTERVAL_SECS:-60}"
PCAP_ON="${BENCH_PCAP:-1}"
PCAP_PER_PHASE="${BENCH_PCAP_PER_PHASE:-0}"
PCAP_CYCLE_SECS="${BENCH_PCAP_CYCLE_SECS:-120}"
PCAP_PHASE_SECS="${BENCH_PCAP_PHASE_SECS:-15}"
ARTIFACTS="${BENCH_ARTIFACTS:-$ROOT/artifacts/bench_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$ARTIFACTS"

DEV="$BENCH_BACNET_DEVICE"
READ_TYPE="$BENCH_BACNET_READ_TYPE"
READ_INST="$BENCH_BACNET_READ_INST"
OVR_TYPE="$BENCH_BACNET_OVR_TYPE"
OVR_INST="$BENCH_BACNET_OVR_INST"
EXPECT_PRIORITY="$BENCH_BACNET_EXPECT_PRIORITY"
EXPECT_VALUE="$BENCH_BACNET_EXPECT_VALUE"
WRITE_PRIORITY="$BENCH_BACNET_WRITE_PRIORITY"

PASS=0
FAIL=0
PCAP_FAIL=0
GREEN=$'\033[32m'; RED=$'\033[31m'; YEL=$'\033[33m'; DIM=$'\033[2m'; BOLD=$'\033[1m'; RST=$'\033[0m'

ok()  { PASS=$((PASS+1)); echo "${GREEN}PASS${RST} $*"; }
bad() { FAIL=$((FAIL+1)); echo "${RED}FAIL${RST} $*" >&2; }
hdr() { echo; echo "${BOLD}== $* ==${RST}"; }
note() { echo "${DIM}  $*${RST}"; }

jq_ok() {
  local label="$1" json="$2"; shift 2
  if [[ -z "$json" ]]; then bad "$label (empty response)"; return 1; fi
  if jq -e "$@" >/dev/null 2>&1 <<<"$json"; then ok "$label"; else bad "$label"; note "$(jq -c . <<<"$json" 2>/dev/null | head -c 400)"; fi
}

save_json() {
  local name="$1" json="$2"
  printf '%s\n' "$json" >"$ARTIFACTS/${name}.json"
}

# Run API call under a short PCAP window; validate expected BACnet frames when tshark available.
pcap_phase() {
  local phase="$1" min_frames="$2" tshark_filter="$3"
  shift 3
  local pcap="$ARTIFACTS/pcap_${phase}.pcap"
  local json_out="$ARTIFACTS/api_${phase}.json"

  if [[ "$PCAP_ON" != "1" ]]; then
    if out="$("$@")"; then save_json "$phase" "$out"; jq_ok "api:$phase" "$out" '. != null'; return; fi
    bad "api:$phase"; return 1
  fi

  local pid
  pid="$(bench_capture_start "$pcap" "$PCAP_PHASE_SECS")"
  sleep 4
  local out=""
  if out="$("$@")"; then
    save_json "$phase" "$out"
    jq_ok "api:$phase" "$out" '. != null'
  else
    bad "api:$phase"
  fi
  sleep 1
  if [[ -n "$pid" ]]; then
    bench_capture_stop "$pid"
  fi
  bench_capture_wait "$pid"

  if [[ ! -f "$pcap" ]] || [[ ! -s "$pcap" ]]; then
    echo "${YEL}WARN${RST} pcap:$phase — no capture (docker netshoot or sudo tcpdump required)"
    return 0
  fi

  local frames udp_frames
  udp_frames="$(bench_pcap_frames "$pcap")"
  if command -v tshark >/dev/null 2>&1 || command -v docker >/dev/null 2>&1; then
    frames="$(bench_pcap_frames "$pcap" "$tshark_filter")"
    if (( frames >= min_frames )); then
      ok "pcap:$phase ($frames matching, $udp_frames udp total)"
    else
      PCAP_FAIL=$((PCAP_FAIL+1))
      bad "pcap:$phase expected >=$min_frames frames matching filter, got $frames ($udp_frames udp total)"
    fi
  else
    if (( udp_frames >= 1 )); then
      ok "pcap:$phase ($udp_frames udp frames — tshark absent, skipped APDU filter)"
    else
      PCAP_FAIL=$((PCAP_FAIL+1))
      bad "pcap:$phase no udp/${BENCH_BACNET_UDP_PORT} frames"
    fi
  fi
}

run_bacnet_cycle() {
  local cycle="${1:-1}"

  if [[ "$PCAP_ON" == "1" && "$PCAP_PER_PHASE" == "1" ]]; then
    hdr "Cycle $cycle — BACnet per-phase PCAP"
    run_bacnet_cycle_per_phase "$cycle"
    validate_key_pcaps
    return
  fi

  local pcap_pid="" combined_pcap="$ARTIFACTS/pcap_cycle_${cycle}.pcap"

  hdr "Cycle $cycle — BACnet client${PCAP_ON:+ + PCAP}"

  if [[ "$PCAP_ON" == "1" && "$PCAP_PER_PHASE" != "1" ]]; then
    pcap_pid="$(bench_capture_start "$combined_pcap" "$PCAP_CYCLE_SECS")"
    sleep 5
  fi

  local whois read rpm discover pa sup write rel dr poll ps

  whois="$(bench_api -X POST "$BENCH_BASE/bacnet/whois" -d "{\"low\":$DEV,\"high\":$DEV}")"
  save_json "whois_c${cycle}" "$whois"
  jq_ok "whois finds device $DEV" "$whois" --arg d "$DEV" 'any(.devices[]; (.device_instance|tostring)==$d)'

  read="$(bench_api -X POST "$BENCH_BASE/bacnet/read" \
    -d "{\"device_instance\":$DEV,\"object_type\":\"$READ_TYPE\",\"object_instance\":$READ_INST}")"
  save_json "read_c${cycle}" "$read"
  jq_ok "read $READ_TYPE:$READ_INST" "$read" '.value != null'

  rpm="$(bench_api -X POST "$BENCH_BASE/bacnet/rpm" \
    -d "{\"device_instance\":$DEV,\"objects\":[{\"object_type\":\"$READ_TYPE\",\"object_instance\":$READ_INST,\"properties\":[{\"property_id\":\"present-value\"}]}]}")"
  save_json "rpm_c${cycle}" "$rpm"
  jq_ok "rpm" "$rpm" '(.results|length)>0'

  discover="$(bench_apis -X POST "$BENCH_BASE/api/bacnet/point-discovery" -d "{\"device_instance\":$DEV}")"
  save_json "discover_c${cycle}" "$discover"
  jq_ok "discover $OVR_TYPE,$OVR_INST commandable" "$discover" \
    --arg oi "$OVR_TYPE,$OVR_INST" 'any(.objects[]; .object_identifier==$oi and .commandable==true)'

  pa="$(bench_api -X POST "$BENCH_BASE/bacnet/priority-array" \
    -d "{\"device_instance\":$DEV,\"object_type\":\"$OVR_TYPE\",\"object_instance\":$OVR_INST}")"
  save_json "priority_array_c${cycle}" "$pa"
  local pv
  pv="$(jq -r --argjson p "$EXPECT_PRIORITY" '.priority_array[]? | select(.priority_level==$p) | .value // empty' <<<"$pa" 2>/dev/null)"
  if [[ -n "$pv" ]] && bench_approx "$pv" "$EXPECT_VALUE"; then
    ok "priority-array P${EXPECT_PRIORITY}=${pv} (~${EXPECT_VALUE}%)"
  else
    bad "priority-array P${EXPECT_PRIORITY}='${pv}' (expected ~${EXPECT_VALUE})"
  fi

  sup="$(bench_apis -X POST "$BENCH_BASE/bacnet/supervisory" -d "{\"device_instance\":$DEV}")"
  save_json "supervisory_c${cycle}" "$sup"
  jq_ok "supervisory P${EXPECT_PRIORITY} override" "$sup" \
    --arg oi "$OVR_TYPE,$OVR_INST" --argjson p "$EXPECT_PRIORITY" \
    'any(.points_with_overrides[]; .object_identifier==$oi and (.override_priority_levels|index($p)))'

  write="$(bench_api -X POST "$BENCH_BASE/bacnet/write" \
    -d "{\"device_instance\":$DEV,\"object_type\":\"$OVR_TYPE\",\"object_instance\":$OVR_INST,\"value\":42.0,\"priority\":$WRITE_PRIORITY,\"approved\":true}")"
  save_json "write_c${cycle}" "$write"
  jq_ok "write @ P${WRITE_PRIORITY}" "$write" '.status=="success"'

  rel="$(bench_api -X POST "$BENCH_BASE/bacnet/write" \
    -d "{\"device_instance\":$DEV,\"object_type\":\"$OVR_TYPE\",\"object_instance\":$OVR_INST,\"value\":null,\"priority\":$WRITE_PRIORITY,\"approved\":true}")"
  save_json "release_c${cycle}" "$rel"
  jq_ok "release null @ P${WRITE_PRIORITY}" "$rel" '.released==true'

  dr="$(bench_api -X POST "$BENCH_BASE/bacnet/write-dry-run" \
    -d "{\"device_instance\":$DEV,\"object_type\":\"$OVR_TYPE\",\"object_instance\":$OVR_INST,\"value\":null,\"priority\":$WRITE_PRIORITY}")"
  jq_ok "write-dry-run" "$dr" '.dry_run==true'

  poll="$(bench_apis -X POST "$BENCH_BASE/bacnet/poll/once")"
  save_json "poll_once_c${cycle}" "$poll"
  jq_ok "poll/once" "$poll" '.points_polled>0'

  ps="$(bench_api "$BENCH_BASE/bacnet/poll/status")"
  jq_ok "poll/status" "$ps" '.points_tracked>0'

  if [[ "$PCAP_ON" == "1" ]]; then
    sleep 2
    if [[ -n "$pcap_pid" ]]; then
      kill "$pcap_pid" 2>/dev/null || true
    fi
    bench_capture_wait "$pcap_pid"
    validate_cycle_pcap "$combined_pcap" "$cycle"
  fi
}

validate_cycle_pcap() {
  local pcap="$1" cycle="$2"
  if [[ ! -s "$pcap" ]]; then
    PCAP_FAIL=$((PCAP_FAIL+1))
    bad "pcap cycle $cycle — no capture (docker netshoot or sudo tcpdump required)"
    return
  fi
  local udp_frames
  udp_frames="$(bench_pcap_frames "$pcap")"
  note "pcap cycle $cycle: $udp_frames udp/${BENCH_BACNET_UDP_PORT} frames → $pcap"

  if ! PCAP_FILE="$pcap" \
    PCAP_MIN_IAM="${PCAP_MIN_IAM:-1}" \
    PCAP_MIN_WHOIS="${PCAP_MIN_WHOIS:-1}" \
    PCAP_MIN_READ="${PCAP_MIN_READ:-2}" \
    PCAP_MIN_RPM="${PCAP_MIN_RPM:-1}" \
    PCAP_MIN_WRITE="${PCAP_MIN_WRITE:-2}" \
    "$SCRIPT_DIR/pcap_validate_docker.sh"; then
    PCAP_FAIL=$((PCAP_FAIL+1))
    bad "pcap cycle $cycle APDU validation failed"
  else
    ok "pcap cycle $cycle APDU validation passed"
  fi
}

validate_key_pcaps() {
  [[ "$PCAP_ON" != "1" ]] && return 0
  hdr "PCAP APDU validation (discover + supervisory)"
  local phase pcap
  for phase in discover supervisory; do
    pcap="$ARTIFACTS/pcap_${phase}.pcap"
    if [[ ! -s "$pcap" ]]; then
      PCAP_FAIL=$((PCAP_FAIL+1))
      bad "pcap validate:$phase — missing capture"
      continue
    fi
    if PCAP_FILE="$pcap" \
      PCAP_MIN_IAM=0 \
      PCAP_MIN_WHOIS=0 \
      PCAP_MIN_READ=1 \
      PCAP_MIN_RPM=1 \
      PCAP_MIN_WRITE=0 \
      "$SCRIPT_DIR/pcap_validate_docker.sh"; then
      ok "pcap validate:$phase APDU gate passed"
    else
      PCAP_FAIL=$((PCAP_FAIL+1))
      bad "pcap validate:$phase APDU gate failed"
    fi
  done
}

run_bacnet_cycle_per_phase() {
  local cycle="$1"
  pcap_phase whois 1 "$(bench_pcap_filter_whois)" \
    bench_api -X POST "$BENCH_BASE/bacnet/whois" -d '{}'
  pcap_phase read 1 "$(bench_pcap_filter_read)" \
    bench_api -X POST "$BENCH_BASE/bacnet/read" \
    -d "{\"device_instance\":$DEV,\"object_type\":\"$READ_TYPE\",\"object_instance\":$READ_INST}"
  pcap_phase rpm 1 "$(bench_pcap_filter_rpm)" \
    bench_api -X POST "$BENCH_BASE/bacnet/rpm" \
    -d "{\"device_instance\":$DEV,\"objects\":[{\"object_type\":\"$READ_TYPE\",\"object_instance\":$READ_INST,\"properties\":[{\"property_id\":\"present-value\"}]}]}"
  pcap_phase discover 1 "$(bench_pcap_filter_read)" \
    bench_apis -X POST "$BENCH_BASE/api/bacnet/point-discovery" -d "{\"device_instance\":$DEV}"
  pcap_phase supervisory 1 "$(bench_pcap_filter_read)" \
    bench_apis -X POST "$BENCH_BASE/bacnet/supervisory" -d "{\"device_instance\":$DEV}"
  pcap_phase write 1 "$(bench_pcap_filter_write)" \
    bench_api -X POST "$BENCH_BASE/bacnet/write" \
    -d "{\"device_instance\":$DEV,\"object_type\":\"$OVR_TYPE\",\"object_instance\":$OVR_INST,\"value\":42.0,\"priority\":$WRITE_PRIORITY,\"approved\":true}"
  pcap_phase release 1 "$(bench_pcap_filter_write)" \
    bench_api -X POST "$BENCH_BASE/bacnet/write" \
    -d "{\"device_instance\":$DEV,\"object_type\":\"$OVR_TYPE\",\"object_instance\":$OVR_INST,\"value\":null,\"priority\":$WRITE_PRIORITY,\"approved\":true}"
  pcap_phase poll_once 1 "$(bench_pcap_filter_rpm)" \
    bench_apis -X POST "$BENCH_BASE/bacnet/poll/once"
}

# Legacy per-phase PCAP helper (BENCH_PCAP_PER_PHASE=1 only).
run_modbus() {
  hdr "Modbus TCP (POST body host=$BENCH_MODBUS_HOST:$BENCH_MODBUS_PORT unit=$BENCH_MODBUS_UNIT)"
  local mb code
  code="$(curl -s -o "$ARTIFACTS/modbus_read.json" -w "%{http_code}" --max-time "$BENCH_TIMEOUT" \
    "${BENCH_AUTH[@]}" -H 'Content-Type: application/json' -X POST "$BENCH_BASE/modbus/read" \
    -d "$(bench_modbus_body)")"
  mb="$(cat "$ARTIFACTS/modbus_read.json")"
  if [[ "$code" == "200" ]] && jq -e '.ok==true and (.readings|length)>0 and .readings[0].success==true' <<<"$mb" >/dev/null; then
    ok "modbus/read live @ $BENCH_MODBUS_HOST:$BENCH_MODBUS_PORT"
    note "decoded=$(jq -r '.readings[0].decoded' <<<"$mb")"
  elif [[ "$code" == "502" ]]; then
    bad "modbus/read upstream error (device unreachable?)"
    note "$(jq -c . <<<"$mb" 2>/dev/null | head -c 200)"
  else
    bad "modbus/read HTTP $code"
    note "$(jq -c . <<<"$mb" 2>/dev/null | head -c 200)"
  fi
}

run_haystack() {
  hdr "Haystack (gateway env → $BENCH_HAYSTACK_URL user=$BENCH_HAYSTACK_USER)"
  note "Sidecar must be started with matching HAYSTACK_BASE_URL / HAYSTACK_AUTH_MODE=basic for Niagara"

  local ha hr hn
  ha="$(bench_api "$BENCH_BASE/haystack/about" 2>/dev/null || true)"
  if jq_ok "haystack/about" "$ha" '.about.count>=1'; then
    save_json haystack_about "$ha"
  else
    note "If SCRAM auth failed, restart gateway with HAYSTACK_AUTH_MODE=basic"
  fi

  hr="$(bench_api -X POST "$BENCH_BASE/haystack/read" -d "{\"filter\":\"$BENCH_HAYSTACK_FILTER\"}" 2>/dev/null || true)"
  jq_ok "haystack/read" "$hr" '.grid.count>=0'

  hn="$(bench_api -X POST "$BENCH_BASE/haystack/nav" -d '{}' 2>/dev/null || true)"
  jq_ok "haystack/nav" "$hn" '.ok==true'

  if [[ -n "$BENCH_HAYSTACK_HIS_ID" ]]; then
    local hh
    hh="$(bench_api -X POST "$BENCH_BASE/haystack/his-read" \
      -d "{\"ids\":[\"$BENCH_HAYSTACK_HIS_ID\"],\"range_start\":\"today\"}" 2>/dev/null || true)"
    jq_ok "haystack/his-read" "$hh" '.ok==true'
  else
    note "haystack/his-read skipped (set BENCH_HAYSTACK_HIS_ID to enable)"
  fi
}

run_hosted_and_health() {
  hdr "Hosted server + health"
  local h o
  h="$(bench_api "$BENCH_BASE/api/health")"
  jq_ok "GET /api/health" "$h" '.ok==true'
  note "service=$(jq -r .service <<<"$h") git_sha=$(jq -r .git_sha <<<"$h")"

  o="$(bench_api "$BENCH_BASE/bacnet/server/objects")"
  jq_ok "server/objects weather AV:9101" "$o" 'any(.objects[]; .name=="outside-air-temperature" and .instance==9101)'

  local wx
  wx="$(bench_api "$BENCH_BASE/weather")"
  jq_ok "weather" "$wx" '.temp_f != null'
}

echo "${BOLD}diy-bacnet-server bench test${RST}"
echo "base=$BENCH_BASE device=$DEV override=${OVR_TYPE}:${OVR_INST} P${EXPECT_PRIORITY}=${EXPECT_VALUE}"
echo "modbus=$BENCH_MODBUS_HOST:$BENCH_MODBUS_PORT haystack=$BENCH_HAYSTACK_URL"
echo "artifacts=$ARTIFACTS minutes=${MINUTES} pcap=${PCAP_ON}"
[[ -z "${OPENFDD_FIELDBUS_API_KEY:-}" ]] && echo "${YEL}(no API key — assuming auth disabled)${RST}"

run_hosted_and_health

CYCLES=0
END=$(( $(date +%s) + MINUTES * 60 ))

while :; do
  CYCLES=$((CYCLES+1))
  run_bacnet_cycle "$CYCLES"
  run_modbus
  run_haystack

  now=$(date +%s)
  [[ "$MINUTES" -eq 0 ]] && break
  [[ "$now" -ge "$END" ]] && break

  sleep_left=$(( INTERVAL - 10 ))
  [[ "$sleep_left" -lt 5 ]] && sleep_left=5
  note "sleep ${sleep_left}s before cycle $((CYCLES+1)) ($(( (END-now)/60 ))m left)"
  sleep "$sleep_left"
done

# Aggregate PCAP gate skipped — validated per cycle in validate_cycle_pcap
echo
echo "${BOLD}Bench summary: ${GREEN}${PASS} passed${RST}, ${RED}${FAIL} failed${RST}, pcap_fail=${PCAP_FAIL} (${CYCLES} cycle(s))${RST}"
echo "artifacts: $ARTIFACTS"

TOTAL_FAIL=$(( FAIL + PCAP_FAIL ))
[[ "$TOTAL_FAIL" -eq 0 ]] || { echo "${RED}BENCH TEST FAILED${RST}" >&2; exit 1; }
echo "${GREEN}BENCH TEST PASSED${RST}"
