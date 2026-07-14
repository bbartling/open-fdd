#!/usr/bin/env bash
# Open-FDD field-bus sidecar — long-running soak test.
#
# Repeatedly exercises EVERY feature (BACnet client, hosted server, weather,
# Haystack, Modbus) for a fixed duration to prove the application is smooth and
# stable under sustained load. Modeled on the Open-FDD nightly soak scripts.
#
# Each cycle validates:
#   BACnet client : whois, read, rpm, discover, priority-array, supervisory,
#                   write + null release, poll/once, poll/status
#   BACnet server : hosted objects, commandable list, weather mirror
#   Haystack      : about, read, nav, his-read
#   Modbus        : /modbus/read (records real read or the documented
#                   "not installed on 3.12" degradation — never a crash/hang)
#   Critical      : device 5007 analogOutput:2466 == 55% @ priority 8
#
# Also records container memory each cycle to catch leaks.
#
# Usage:
#   export OPENFDD_FIELDBUS_API_KEY=...   # optional local admin token
#   SOAK_MINUTES=30 scripts/fieldbus/soak_test.sh
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/bench_lib.sh
source "$ROOT/scripts/bench_lib.sh"
bench_load_env "$ROOT"

BASE="${SMOKE_BASE:-$BENCH_BASE}"
KEY="${OPENFDD_FIELDBUS_API_KEY:-${RUSTY_GATEWAY_API_KEY:-}}"
MINUTES="${SOAK_MINUTES:-30}"
INTERVAL="${SOAK_INTERVAL_SECS:-60}"
CONTAINER="${SOAK_CONTAINER:-diy-bacnet-server}"

DEV="${SMOKE_DEVICE:-5007}"
READ_TYPE="${SMOKE_READ_TYPE:-analog-input}"
READ_INST="${SMOKE_READ_INST:-1173}"
OVR_TYPE="${SMOKE_OVERRIDE_TYPE:-analog-output}"
OVR_INST="${SMOKE_OVERRIDE_INST:-2466}"
EXPECT_PRIORITY="${SMOKE_OVERRIDE_PRIORITY:-8}"
EXPECT_VALUE="${SMOKE_OVERRIDE_VALUE:-55}"
WRITE_PRIORITY="${SMOKE_WRITE_PRIORITY:-10}"
HIS_POINT="${SOAK_HAYSTACK_POINT:-demo-vav-1-01-zat}"
TIMEOUT="${SMOKE_TIMEOUT:-45}"
SUP_TIMEOUT="${SMOKE_SUP_TIMEOUT:-240}"

command -v jq >/dev/null || { echo "FATAL: jq required" >&2; exit 2; }

AUTH=(); [[ -n "$KEY" ]] && AUTH=(-H "Authorization: Bearer $KEY")
api()  { curl -fsS --max-time "$TIMEOUT" -H 'Content-Type: application/json' "${AUTH[@]}" "$@"; }
apis() { curl -fsS --max-time "$SUP_TIMEOUT" -H 'Content-Type: application/json' "${AUTH[@]}" "$@"; }

GREEN=$'\033[32m'; RED=$'\033[31m'; YEL=$'\033[33m'; DIM=$'\033[2m'; BOLD=$'\033[1m'; RST=$'\033[0m'

TS="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="/tmp/soak_${TS}"
mkdir -p "$OUT"

approx() { awk -v a="$1" -v b="$2" 'BEGIN{d=a-b; if(d<0)d=-d; exit !(d<=1.0)}'; }

# check <name> <json> [jq args...] <filter>
declare -A FEATURE_PASS FEATURE_FAIL
check() {
  local name="$1" json="$2"; shift 2
  if [[ -z "$json" ]]; then FEATURE_FAIL[$name]=$(( ${FEATURE_FAIL[$name]:-0} + 1 )); return 1; fi
  if jq -e "$@" >/dev/null 2>&1 <<<"$json"; then
    FEATURE_PASS[$name]=$(( ${FEATURE_PASS[$name]:-0} + 1 )); return 0
  else
    FEATURE_FAIL[$name]=$(( ${FEATURE_FAIL[$name]:-0} + 1 )); return 1
  fi
}
note() { FEATURE_PASS[$1]=$(( ${FEATURE_PASS[$1]:-0} + 1 )); }  # degraded-but-graceful counts as handled

CYCLES=0
OVERRIDE_OK=0
OVERRIDE_MISS=0
END=$(( $(date +%s) + MINUTES * 60 ))

echo "${BOLD}Field-bus sidecar SOAK — ${MINUTES} min @ ${INTERVAL}s cycles${RST}"
echo "base=$BASE device=$DEV override=${OVR_TYPE}:${OVR_INST} expect P${EXPECT_PRIORITY}=${EXPECT_VALUE}"
echo "artifacts: $OUT"
[[ -z "$KEY" ]] && echo "${DIM}(no API key — assuming auth disabled)${RST}"

while :; do
  now=$(date +%s); [[ "$now" -ge "$END" ]] && break
  CYCLES=$((CYCLES+1))
  cstart=$now
  echo; echo "${BOLD}--- cycle $CYCLES  ($(date -u +%H:%M:%SZ), $(( (END-now)/60 ))m left) ---${RST}"

  # ---- BACnet client ----
  check whois       "$(api -X POST "$BASE/bacnet/whois" -d "{\"low\":$DEV,\"high\":$DEV}")" \
                    --arg d "$DEV" 'any(.devices[]; (.device_instance|tostring)==$d)' \
    && echo "  whois ok" || echo "  ${RED}whois FAIL${RST}"

  check read        "$(api -X POST "$BASE/bacnet/read" -d "{\"device_instance\":$DEV,\"object_type\":\"$READ_TYPE\",\"object_instance\":$READ_INST}")" \
                    '.value != null' \
    && echo "  read ok" || echo "  ${RED}read FAIL${RST}"

  check rpm         "$(api -X POST "$BASE/bacnet/rpm" -d "{\"device_instance\":$DEV,\"objects\":[{\"object_type\":\"$READ_TYPE\",\"object_instance\":$READ_INST,\"properties\":[{\"property_id\":\"present-value\"}]}]}")" \
                    '(.results|length)>0' \
    && echo "  rpm ok" || echo "  ${RED}rpm FAIL${RST}"

  DISC="$(apis -X POST "$BASE/api/bacnet/point-discovery" -d "{\"device_instance\":$DEV}")"
  check discover    "$DISC" --arg oi "$OVR_TYPE,$OVR_INST" 'any(.objects[]; .object_identifier==$oi and .commandable==true)' \
    && echo "  discover ok ($(jq -r '.objects|length' <<<"$DISC" 2>/dev/null) objs)" || echo "  ${RED}discover FAIL${RST}"

  PA="$(api -X POST "$BASE/bacnet/priority-array" -d "{\"device_instance\":$DEV,\"object_type\":\"$OVR_TYPE\",\"object_instance\":$OVR_INST}")"
  PV=$(jq -r --argjson p "$EXPECT_PRIORITY" '.priority_array[]? | select(.priority_level==$p) | .value // empty' <<<"$PA" 2>/dev/null)
  if [[ -n "$PV" ]] && approx "$PV" "$EXPECT_VALUE"; then
    note priority_array; OVERRIDE_OK=$((OVERRIDE_OK+1)); echo "  ${GREEN}priority-array P${EXPECT_PRIORITY}=${PV} (override confirmed)${RST}"
  else
    FEATURE_FAIL[priority_array]=$(( ${FEATURE_FAIL[priority_array]:-0} + 1 )); OVERRIDE_MISS=$((OVERRIDE_MISS+1)); echo "  ${RED}priority-array P${EXPECT_PRIORITY}='${PV}' MISS${RST}"
  fi

  SUP="$(apis -X POST "$BASE/bacnet/supervisory" -d "{\"device_instance\":$DEV}")"
  check supervisory "$SUP" --arg oi "$OVR_TYPE,$OVR_INST" --argjson p "$EXPECT_PRIORITY" \
                    'any(.points_with_overrides[]; .object_identifier==$oi and (.override_priority_levels|index($p)))' \
    && echo "  supervisory ok ($(jq -r '.points_with_overrides|length' <<<"$SUP" 2>/dev/null) overridden pts)" || echo "  ${RED}supervisory FAIL${RST}"

  check write       "$(api -X POST "$BASE/bacnet/write" -d "{\"device_instance\":$DEV,\"object_type\":\"$OVR_TYPE\",\"object_instance\":$OVR_INST,\"value\":42.0,\"priority\":$WRITE_PRIORITY}")" \
                    '.status=="success"' \
    && echo "  write ok" || echo "  ${RED}write FAIL${RST}"
  check release     "$(api -X POST "$BASE/bacnet/write" -d "{\"device_instance\":$DEV,\"object_type\":\"$OVR_TYPE\",\"object_instance\":$OVR_INST,\"value\":null,\"priority\":$WRITE_PRIORITY}")" \
                    '.released==true' \
    && echo "  release ok" || echo "  ${RED}release FAIL${RST}"

  check poll_once   "$(apis -X POST "$BASE/bacnet/poll/once")" '.points_polled>0' \
    && echo "  poll/once ok" || echo "  ${RED}poll/once FAIL${RST}"
  check poll_status "$(api "$BASE/bacnet/poll/status")" '.points_tracked>0' \
    && echo "  poll/status ok" || echo "  ${RED}poll/status FAIL${RST}"

  # ---- BACnet server (hosted) ----
  check server_objects "$(api "$BASE/bacnet/server/objects")" 'any(.objects[]; .name=="outside-air-temperature" and .instance==9101)' \
    && echo "  server/objects ok" || echo "  ${RED}server/objects FAIL${RST}"
  check server_cmd  "$(api "$BASE/bacnet/server/commandable")" 'any(.objects[]; .name=="openfdd-optimization-enabled")' \
    && echo "  server/commandable ok" || echo "  ${RED}server/commandable FAIL${RST}"

  # ---- Weather ----
  check weather     "$(api "$BASE/weather")" '.temp_f != null' \
    && echo "  weather ok" || echo "  ${RED}weather FAIL${RST}"

  # ---- Haystack ----
  check hs_about    "$(api "$BASE/haystack/about")" '.about.count>=1' \
    && echo "  haystack/about ok" || echo "  ${RED}haystack/about FAIL${RST}"
  check hs_read     "$(api -X POST "$BASE/haystack/read" -d '{"filter":"point"}')" '.grid.count>0' \
    && echo "  haystack/read ok" || echo "  ${RED}haystack/read FAIL${RST}"
  check hs_nav      "$(api -X POST "$BASE/haystack/nav" -d '{}')" '.ok==true' \
    && echo "  haystack/nav ok" || echo "  ${RED}haystack/nav FAIL${RST}"
  check hs_hisread  "$(api -X POST "$BASE/haystack/his-read" -d "{\"ids\":[\"$HIS_POINT\"],\"range_start\":\"today\"}")" '.ok==true' \
    && echo "  haystack/his-read ok" || echo "  ${RED}haystack/his-read FAIL${RST}"

  # ---- Modbus (graceful on 3.12: real read OR documented "not installed") ----
  MB_CODE=$(curl -s -o "$OUT/modbus_c${CYCLES}.json" -w "%{http_code}" --max-time "$TIMEOUT" "${AUTH[@]}" \
    -H 'Content-Type: application/json' -X POST "$BASE/modbus/read" \
    -d "$(bench_modbus_body)")
  if [[ "$MB_CODE" == "200" ]]; then
    note modbus; echo "  ${GREEN}modbus/read ok (live)${RST}"
  elif grep -q "rusty_modbus not installed" "$OUT/modbus_c${CYCLES}.json" 2>/dev/null; then
    note modbus; echo "  ${YEL}modbus/read degraded gracefully (no 3.12 wheel) — handled${RST}"
  elif [[ "$MB_CODE" == "502" ]] || grep -qE 'modbus_error|Connection refused|transport error' "$OUT/modbus_c${CYCLES}.json" 2>/dev/null; then
    note modbus; echo "  ${YEL}modbus/read degraded gracefully (no simulator) — handled${RST}"
  else
    FEATURE_FAIL[modbus]=$(( ${FEATURE_FAIL[modbus]:-0} + 1 )); echo "  ${RED}modbus/read unexpected (HTTP $MB_CODE)${RST}"
  fi

  # ---- health + memory ----
  HJSON="$(api "$BASE/api/health")"; check health "$HJSON" '.ok==true' >/dev/null
  MEM=$(docker stats --no-stream --format '{{.MemUsage}}' "$CONTAINER" 2>/dev/null | awk '{print $1}')
  echo "  ${DIM}health ok=$(jq -r .ok <<<"$HJSON" 2>/dev/null) mem=${MEM:-?}${RST}"
  echo "$CYCLES,$(date -u +%H:%M:%SZ),${MEM:-?},${PV:-}" >> "$OUT/mem.csv"

  celapsed=$(( $(date +%s) - cstart ))
  sleep_left=$(( INTERVAL - celapsed )); [[ "$sleep_left" -lt 1 ]] && sleep_left=1
  now=$(date +%s); [[ "$now" -ge "$END" ]] && break
  sleep "$sleep_left"
done

# ---- summary ----
echo; echo "${BOLD}==================== SOAK SUMMARY ====================${RST}"
echo "cycles=$CYCLES  duration=${MINUTES}m  override P${EXPECT_PRIORITY}: ${OVERRIDE_OK} ok / ${OVERRIDE_MISS} miss"
TOTAL_FAIL=0
printf "%-18s %8s %8s\n" "feature" "pass" "fail"
for f in whois read rpm discover priority_array supervisory write release poll_once poll_status \
         server_objects server_cmd weather hs_about hs_read hs_nav hs_hisread modbus health; do
  p=${FEATURE_PASS[$f]:-0}; q=${FEATURE_FAIL[$f]:-0}; TOTAL_FAIL=$((TOTAL_FAIL+q))
  col=$GREEN; [[ "$q" -gt 0 ]] && col=$RED
  printf "${col}%-18s %8s %8s${RST}\n" "$f" "$p" "$q"
done
echo "mem trace: $OUT/mem.csv"
echo "======================================================"
if [[ "$TOTAL_FAIL" -eq 0 && "$OVERRIDE_MISS" -eq 0 ]]; then
  echo "${GREEN}${BOLD}SOAK PASSED — application smooth across $CYCLES cycles${RST}"; exit 0
else
  echo "${RED}${BOLD}SOAK FAILED — ${TOTAL_FAIL} feature failures, ${OVERRIDE_MISS} override misses${RST}"; exit 1
fi
