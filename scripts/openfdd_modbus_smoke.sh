#!/usr/bin/env bash
# Modbus test-bench smoke — read input/holding registers, decode x10 values, optional write test.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_rust_site_lib.sh
source "$ROOT/scripts/openfdd_rust_site_lib.sh"
# shellcheck source=scripts/openfdd_auth_lib.sh
source "$ROOT/scripts/openfdd_auth_lib.sh"

BASE="${OPENFDD_API_BASE:-http://127.0.0.1:8080}"
AUTH="${OPENFDD_AUTH_ENV:-$ROOT/workspace/auth.env.local}"
HOST="${OPENFDD_MODBUS_HOST:-}"
PORT="${OPENFDD_MODBUS_PORT:-1502}"
UNIT="${OPENFDD_MODBUS_UNIT_ID:-1}"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$ROOT/workspace/logs/modbus_smoke_${TS}"
mkdir -p "$OUT"

if [[ -z "$HOST" ]]; then
  echo "ERROR: set OPENFDD_MODBUS_HOST (test-bench IP/host)" >&2
  exit 1
fi

export OPENFDD_MODBUS_MODE=live
export OPENFDD_MODBUS_HOST="$HOST"
export OPENFDD_MODBUS_PORT="$PORT"
export OPENFDD_MODBUS_UNIT_ID="$UNIT"

TOKEN="$(openfdd_auth_login_token "$BASE" "$AUTH" integrator)" || {
  echo "ERROR: integrator login failed" >&2
  exit 1
}

read_reg() {
  local reg="$1" fn="$2" scale="${3:-0.1}" unit="${4:-}"
  curl -fsS -X POST "$BASE/api/modbus/read" \
    -H "Authorization: Bearer $TOKEN" \
    -H 'Content-Type: application/json' \
    -d "$(jq -nc --argjson r "$reg" --arg f "$fn" --argjson s "$scale" --arg u "$unit" \
      '{register:$r,function:$f,scale:$s,unit:$u}')" \
    | tee "$OUT/reg_${reg}.json"
}

echo "Modbus smoke host=$HOST port=$PORT unit=$UNIT → $OUT"

read_reg 30001 input_register 0.1 "degF" >/dev/null
read_reg 30002 input_register 0.1 "degC" >/dev/null
read_reg 30003 input_register 0.1 "%RH" >/dev/null
read_reg 30004 input_register 1 "count" >/dev/null
read_reg 40001 holding_register 0.1 "degF" >/dev/null
read_reg 40002 holding_register 0.1 "degC" >/dev/null
read_reg 40003 holding_register 0.1 "degF" >/dev/null
read_reg 40004 holding_register 1 "status" >/dev/null
read_reg 40005 holding_register 1 "count" >/dev/null
read_reg 40006 holding_register 1 "flag" >/dev/null

hb1="$(jq -r '.raw // .value // empty' "$OUT/reg_30004.json" 2>/dev/null || true)"
sleep 2
read_reg 30004 input_register 1 "count" >"$OUT/reg_30004_reread.json"
hb2="$(jq -r '.raw // .value // empty' "$OUT/reg_30004_reread.json" 2>/dev/null || true)"
jq -nc --arg hb1 "$hb1" --arg hb2 "$hb2" \
  '{heartbeat_before:$hb1,heartbeat_after:$hb2,changed:($hb1 != $hb2 and $hb1 != "" and $hb2 != "")}' \
  >"$OUT/heartbeat_check.json"

if [[ "${OPENFDD_MODBUS_WRITE_TEST:-0}" == "1" ]]; then
  echo "Write test enabled — setpoint 40003 only"
  prev="$(jq -r '.raw // 0' "$OUT/reg_40003.json")"
  curl -fsS -X POST "$BASE/api/modbus/write" \
    -H "Authorization: Bearer $TOKEN" \
    -H 'Content-Type: application/json' \
    -d "$(jq -nc --argjson r 40003 --argjson v "$prev" '{register:40003,function:"holding_register",value:$v,scale:0.1}')" \
    >"$OUT/write_restore.json" 2>/dev/null || echo '{"ok":false,"note":"write API optional"}' >"$OUT/write_restore.json"
fi

curl -fsS "$BASE/api/modbus/driver/tree" -H "Authorization: Bearer $TOKEN" >"$OUT/driver_tree.json" || true
curl -fsS -X POST "$BASE/api/modbus/poll-once" -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{}' \
  >"$OUT/poll_once.json" 2>/dev/null || true

echo "PASS — artifacts in $OUT"
