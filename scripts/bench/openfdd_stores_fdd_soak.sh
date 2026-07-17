#!/usr/bin/env bash
# Soak test: every 60s verify historian/Arrow stores grow + FDD cycle runs + drivers poll.
#
# Usage:
#   ./scripts/openfdd_stores_fdd_soak.sh
#   OPENFDD_SOAK_MINUTES=10 OPENFDD_SOAK_INTERVAL_SEC=60 ./scripts/openfdd_stores_fdd_soak.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=scripts/openfdd_auth_lib.sh
source "$ROOT/scripts/openfdd_auth_lib.sh"
# shellcheck source=scripts/openfdd_stack_lib.sh
source "$ROOT/scripts/openfdd_stack_lib.sh"

BASE="${OPENFDD_API_BASE:-http://127.0.0.1:8080}"
COMMISSION="${OPENFDD_COMMISSION_BASE:-http://127.0.0.1:9091}"
AUTH="${OPENFDD_AUTH_ENV:-$ROOT/workspace/auth.env.local}"
MINUTES="${OPENFDD_SOAK_MINUTES:-10}"
INTERVAL="${OPENFDD_SOAK_INTERVAL_SEC:-60}"
CYCLES=$(( (MINUTES * 60) / INTERVAL ))
[[ "$CYCLES" -lt 1 ]] && CYCLES=1

RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${OPENFDD_SOAK_DIR:-$ROOT/workspace/logs/soak_${MINUTES}m_${RUN_TS}}"
HIST_DIR="${OPENFDD_HISTORIAN_HOST_PATH:-$ROOT/workspace/data/historian/validation}"

mkdir -p "$OUT"
CURL_TLS=()
[[ "$BASE" == https://* ]] && CURL_TLS=(-k)

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$OUT/soak.log"; }

TOKEN="$(openfdd_auth_login_token "$BASE" "$AUTH" integrator)" || {
  echo "ERROR: login failed" >&2; exit 1
}
AGENT_TOKEN="$(openfdd_auth_login_token "$BASE" "$AUTH" agent 2>/dev/null || true)"
[[ -n "$AGENT_TOKEN" ]] || AGENT_TOKEN="$TOKEN"
auth=(-H "Authorization: Bearer $TOKEN")
auth_agent=(-H "Authorization: Bearer $AGENT_TOKEN")

arrow_bytes() {
  local f="$HIST_DIR/telemetry_pivot.arrow"
  [[ -f "$f" ]] && wc -c <"$f" | tr -d ' ' || echo 0
}

jsonl_lines() {
  local f="$HIST_DIR/telemetry_pivot.jsonl"
  [[ -f "$f" ]] && wc -l <"$f" | tr -d ' ' || echo 0
}

log "Soak ${MINUTES}m (${CYCLES} samples @ ${INTERVAL}s) → $OUT"
: >"$OUT/soak_samples.jsonl"

prev_rows=0
prev_arrow=0
prev_jsonl=0
stalls=0
FAIL=0

for n in $(seq 1 "$CYCLES"); do
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  hist="$(curl "${CURL_TLS[@]}" -fsS "${auth[@]}" "$BASE/api/historian/validation/status" 2>/dev/null || echo '{}')"
  vr="$(curl "${CURL_TLS[@]}" -fsS "${auth[@]}" "$BASE/api/validation-runs/current/status" 2>/dev/null || echo '{}')"
  modbus_ok=false haystack_ok=false bacnet_ok=false fdd_ok=false
  curl "${CURL_TLS[@]}" -fsS "${auth[@]}" "$BASE/api/modbus/poll/status" 2>/dev/null | jq -e '.ok==true' >/dev/null && modbus_ok=true
  # Generate OT wire traffic for pcap validation (status alone does not poll the field device).
  curl "${CURL_TLS[@]}" -fsS -X POST "${auth[@]}" -H 'Content-Type: application/json' \
    "$BASE/api/modbus/read" \
    -d '{"register":30001,"function":"input_register","scale":0.1,"unit":"degF"}' \
    2>/dev/null | jq -e '.ok==true' >/dev/null && modbus_ok=true
  curl "${CURL_TLS[@]}" -fsS -X POST "${auth[@]}" -H 'Content-Type: application/json' \
    "$BASE/api/haystack/test" -d '{}' 2>/dev/null | jq -e '.ok==true' >/dev/null && haystack_ok=true
  curl "${CURL_TLS[@]}" -fsS -X POST "${auth[@]}" -H 'Content-Type: application/json' \
    "$COMMISSION/api/bacnet/whois" -d "$(openfdd_bench_whois_json)" 2>/dev/null \
    | jq -e 'type=="array" and length>0' >/dev/null && bacnet_ok=true

  cycle="$(curl "${CURL_TLS[@]}" -fsS -X POST "${auth_agent[@]}" -H 'Content-Type: application/json' \
    "$BASE/api/validation-runs/current/cycle" -d '{}' 2>/dev/null || echo '{}')"
  echo "$cycle" >"$OUT/cycle_${n}.json"
  jq -e '.ok==true' <<<"$cycle" >/dev/null 2>&1 && fdd_ok=true

  rows="$(jq -r '.row_count // 0' <<<"$hist")"
  arrow="$(arrow_bytes)"
  jsonl="$(jsonl_lines)"
  rows_delta=$(( rows - prev_rows ))
  arrow_delta=$(( arrow - prev_arrow ))
  jsonl_delta=$(( jsonl - prev_jsonl ))

  growing=true
  if [[ "$n" -gt 1 && "$rows_delta" -le 0 && "$arrow_delta" -le 0 && "$jsonl_delta" -le 0 ]]; then
    growing=false
    stalls=$((stalls + 1))
  fi

  jq -nc \
    --arg ts "$ts" --argjson n "$n" \
    --argjson rows "$rows" --argjson rows_delta "$rows_delta" \
    --argjson arrow "$arrow" --argjson arrow_delta "$arrow_delta" \
    --argjson jsonl "$jsonl" --argjson jsonl_delta "$jsonl_delta" \
    --argjson modbus "$modbus_ok" --argjson haystack "$haystack_ok" \
    --argjson bacnet "$bacnet_ok" --argjson fdd "$fdd_ok" \
    --argjson growing "$growing" \
    --argjson raw_fault "$(jq -r '.proof.raw_fault_samples // 0' <<<"$cycle")" \
    --argjson fdd_sql "$(jq -r '.fdd_eval.ok // false' <<<"$cycle")" \
    '{timestamp_utc:$ts,sample:$n,historian_row_count:$rows,historian_row_delta:$rows_delta,
      arrow_bytes:$arrow,arrow_delta:$arrow_delta,jsonl_lines:$jsonl,jsonl_delta:$jsonl_delta,
      modbus_poll_ok:$modbus,haystack_ok:$haystack,bacnet_whois_ok:$bacnet,fdd_cycle_ok:$fdd,
      stores_growing:$growing,raw_fault_samples:$raw_fault,fdd_sql_ok:$fdd_sql}' \
    >>"$OUT/soak_samples.jsonl"

  log "sample=$n rows=$rows (+$rows_delta) arrow=$arrow (+$arrow_delta) modbus=$modbus_ok haystack=$haystack_ok bacnet=$bacnet_ok fdd=$fdd_ok growing=$growing"

  prev_rows=$rows prev_arrow=$arrow prev_jsonl=$jsonl
  [[ "$n" -lt "$CYCLES" ]] && sleep "$INTERVAL"
done

# Allow 1 flat minute; fail if >2 consecutive stalls or final rows==0
flat_limit="${OPENFDD_SOAK_MAX_STALLS:-2}"
if [[ "$stalls" -gt "$flat_limit" ]]; then
  log "FAIL: stores stalled $stalls samples (max $flat_limit)"
  FAIL=1
fi
if [[ "$prev_rows" -eq 0 ]]; then
  log "FAIL: historian row_count still 0 after soak"
  FAIL=1
fi

driver_fails="$(jq -s '[.[] | select(.modbus_poll_ok==false or .haystack_ok==false or .bacnet_whois_ok==false)] | length' "$OUT/soak_samples.jsonl")"
if [[ "$driver_fails" -gt 0 ]]; then
  log "FAIL: $driver_fails soak samples had driver poll failure"
  FAIL=1
fi

jq -nc \
  --arg dir "$OUT" --argjson cycles "$CYCLES" --argjson stalls "$stalls" \
  --argjson fail "$FAIL" --argjson final_rows "$prev_rows" \
  '{artifact_dir:$dir,cycles:$cycles,stall_count:$stalls,final_historian_rows:$final_rows,passed:($fail==0)}' \
  >"$OUT/soak_result.json"

log "Soak complete stalls=$stalls fail=$FAIL"
[[ "$FAIL" -eq 0 ]]
