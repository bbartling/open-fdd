#!/usr/bin/env bash
# Modbus OT gates against the bench temp-sensor simulator (gist modbus_temp_sensor_server.py
# on a bench Pi). Exercises fieldbus POST /modbus/read: IR/HR reads, scaling, heartbeat
# liveness, and negative paths (bad unit id, out-of-range register). Fieldbus must stay
# healthy after error paths.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib.sh"
load_bench_env
auth_setup
cd "$ROOT"

MB_HOST="${MODBUS_SIM_HOST:-192.168.204.14}"
MB_PORT="${MODBUS_SIM_PORT:-1502}"
MB_UNIT="${MODBUS_SIM_UNIT_ID:-1}"
MB_BASE_F="${MODBUS_SIM_BASE_F:-72}"
MB_AMP_F="${MODBUS_SIM_AMPLITUDE_F:-4}"

ART="${ARTIFACT_DIR:-$(artifact_dir)}"
mkdir -p "$ART"

mb_read() {
  # mb_read <unit_id> <registers-json>
  local unit="$1" regs="$2"
  fb -X POST "$FIELDBUS_BASE/modbus/read" -d "$(jq -nc \
    --arg host "$MB_HOST" --argjson port "$MB_PORT" --argjson unit "$unit" \
    --argjson regs "$regs" \
    '{host:$host, port:$port, unit_id:$unit, timeout:5.0, registers:$regs}')"
}

hdr "TCP reachability $MB_HOST:$MB_PORT"
if (echo >"/dev/tcp/$MB_HOST/$MB_PORT") >/dev/null 2>&1; then
  ok "modbus sim TCP port open"
else
  bad "modbus sim $MB_HOST:$MB_PORT unreachable — is the gist server running on the bench Pi?"
  summary
  exit 1
fi

hdr "Input registers 30001-30004 (temp_f, temp_c, humidity, heartbeat)"
IR_SPEC='[
  {"address":0,"count":1,"function":"input","decode":"uint16","scale":0.1,"label":"temp_f"},
  {"address":1,"count":1,"function":"input","decode":"uint16","scale":0.1,"label":"temp_c"},
  {"address":2,"count":1,"function":"input","decode":"uint16","scale":0.1,"label":"humidity"},
  {"address":3,"count":1,"function":"input","decode":"uint16","label":"heartbeat"}
]'
if IR="$(mb_read "$MB_UNIT" "$IR_SPEC" 2>/dev/null)"; then
  echo "$IR" >"$ART/modbus_input_regs.json"
  jq_ok "modbus/read ok=true" "$IR" '.ok==true'
  jq_ok "4 readings, all success" "$IR" '(.readings|length)==4 and all(.readings[]; .success==true)'
  TF="$(jq -r '.readings[0].decoded // empty' <<<"$IR")"
  TC="$(jq -r '.readings[1].decoded // empty' <<<"$IR")"
  HUM="$(jq -r '.readings[2].decoded // empty' <<<"$IR")"
  HB1="$(jq -r '.readings[3].words[0] // empty' <<<"$IR")"
  echo "${DIM}  temp_f=$TF temp_c=$TC humidity=$HUM heartbeat=$HB1${RST}"
  if [[ -n "$TF" ]] && approx "$TF" "$MB_BASE_F" "$(python3 -c "print(float('$MB_AMP_F')+1.5)")"; then
    ok "temp_f $TF within ${MB_BASE_F}±$MB_AMP_F(+1.5) sine envelope"
  else
    bad "temp_f '$TF' outside expected sine envelope ${MB_BASE_F}±$MB_AMP_F"
  fi
  if [[ -n "$TF" && -n "$TC" ]]; then
    EXPECT_C="$(python3 -c "print((float('$TF')-32.0)*5.0/9.0)")"
    if approx "$TC" "$EXPECT_C" 0.3; then
      ok "temp_c $TC consistent with temp_f (F↔C conversion)"
    else
      bad "temp_c $TC inconsistent with temp_f $TF (expected ≈$EXPECT_C)"
    fi
  fi
else
  bad "POST /modbus/read (input regs) failed"
fi

hdr "Holding registers 40001-40006 (temp, setpoint, status, heartbeat, fault)"
HR_SPEC='[
  {"address":0,"count":1,"function":"holding","decode":"uint16","scale":0.1,"label":"temp_f"},
  {"address":2,"count":1,"function":"holding","decode":"uint16","scale":0.1,"label":"setpoint_f"},
  {"address":3,"count":1,"function":"holding","decode":"uint16","label":"status"},
  {"address":5,"count":1,"function":"holding","decode":"uint16","label":"fault"}
]'
if HR="$(mb_read "$MB_UNIT" "$HR_SPEC" 2>/dev/null)"; then
  echo "$HR" >"$ART/modbus_holding_regs.json"
  jq_ok "holding reads all success" "$HR" 'all(.readings[]; .success==true)'
  SP="$(jq -r '.readings[1].decoded // empty' <<<"$HR")"
  ST="$(jq -r '.readings[2].decoded // empty' <<<"$HR")"
  FLT="$(jq -r '.readings[3].decoded // empty' <<<"$HR")"
  echo "${DIM}  setpoint_f=$SP status=$ST fault=$FLT${RST}"
  [[ "$ST" == "1" ]] && ok "status register = 1 (running)" || skip "status=$ST (operator may have written test value)"
  [[ "$FLT" == "0" ]] && ok "fault register = 0 (no fault)" || skip "fault=$FLT (operator may have written test fault)"
else
  bad "POST /modbus/read (holding regs) failed"
fi

hdr "Heartbeat liveness (device is alive, not a stale responder)"
HB_SPEC='[{"address":3,"count":1,"function":"input","decode":"uint16","label":"heartbeat"}]'
HB_A="$(mb_read "$MB_UNIT" "$HB_SPEC" 2>/dev/null | jq -r '.readings[0].words[0] // empty')"
sleep 2
HB_B="$(mb_read "$MB_UNIT" "$HB_SPEC" 2>/dev/null | jq -r '.readings[0].words[0] // empty')"
if [[ -n "$HB_A" && -n "$HB_B" && "$HB_B" != "$HB_A" ]]; then
  ok "heartbeat advanced ($HB_A → $HB_B)"
else
  bad "heartbeat did not advance ($HB_A → $HB_B) — sim frozen or fieldbus caching?"
fi

hdr "Negative: wrong unit id (expect clean Modbus exception, no fieldbus crash)"
set +e
BAD_UNIT_OUT="$(mb_read 7 "$HB_SPEC" 2>&1)"
BAD_UNIT_RC=$?
set -e
echo "$BAD_UNIT_OUT" >"$ART/modbus_bad_unit.json"
if [[ $BAD_UNIT_RC -ne 0 ]] || jq -e 'any(.readings[]?; .success==false) or (.ok==false)' <<<"$BAD_UNIT_OUT" >/dev/null 2>&1; then
  ok "wrong unit id surfaced as error (exception 11 path)"
else
  bad "wrong unit id returned success — gateway not propagating Modbus exceptions"
fi

hdr "Negative: out-of-range register (expect exception 2 / illegal address)"
OOR_SPEC='[{"address":100,"count":1,"function":"input","decode":"uint16","label":"oor"}]'
set +e
OOR_OUT="$(mb_read "$MB_UNIT" "$OOR_SPEC" 2>&1)"
OOR_RC=$?
set -e
echo "$OOR_OUT" >"$ART/modbus_oor.json"
if [[ $OOR_RC -ne 0 ]] || jq -e 'any(.readings[]?; .success==false) or (.ok==false)' <<<"$OOR_OUT" >/dev/null 2>&1; then
  ok "out-of-range register surfaced as error"
else
  bad "out-of-range register returned success — validation gap"
fi

hdr "Fieldbus healthy after Modbus error paths"
if H="$(fb "$FIELDBUS_BASE/health" 2>/dev/null)" && jq -e '.ok==true' <<<"$H" >/dev/null; then
  ok "fieldbus /health ok after negative tests"
else
  bad "fieldbus unhealthy after Modbus negative tests — error handling crashed service"
fi

summary
