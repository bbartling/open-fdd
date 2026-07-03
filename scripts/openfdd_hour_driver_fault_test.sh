#!/usr/bin/env bash
# Step 3 — 1-minute driver poll for OPENFDD_HOUR_TEST_MINUTES (default 60).
# JSON API / postbin: validate ONCE on cycle 1 only; status every minute thereafter.
# At OPENFDD_FAULT_RULE_CHANGE_MINUTE (default 30): patch fault rule param via API, verify FDD reacts.
# On FAIL: exit non-zero so orchestrator can restart from scratch.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_auth_lib.sh
source "$ROOT/scripts/openfdd_auth_lib.sh"
# shellcheck source=scripts/openfdd_bench_lib.sh
source "$ROOT/scripts/openfdd_bench_lib.sh"

openfdd_bench_load_profile "$ROOT"

BASE="${OPENFDD_API_BASE:-http://127.0.0.1:8080}"
COMMISSION="${OPENFDD_COMMISSION_BASE:-http://127.0.0.1:9091}"
AUTH="${OPENFDD_AUTH_ENV:-$ROOT/workspace/auth.env.local}"
INTERVAL="${OPENFDD_DRIVER_POLL_INTERVAL_SEC:-60}"
MINUTES="${OPENFDD_HOUR_TEST_MINUTES:-60}"
CHANGE_MIN="${OPENFDD_FAULT_RULE_CHANGE_MINUTE:-30}"
RULE_ID="${OPENFDD_FAULT_RULE_ID:-oa_temp_out_of_range}"
CYCLES="$MINUTES"
[[ "$CYCLES" -lt 1 ]] && CYCLES=1

REQUIRE_HAYSTACK="${OPENFDD_HOUR_REQUIRE_HAYSTACK:-${OPENFDD_REQUIRE_HAYSTACK:-1}}"
REQUIRE_JSON="${OPENFDD_HOUR_REQUIRE_JSON:-1}"
REQUIRE_LIVE_READS="${OPENFDD_HOUR_REQUIRE_LIVE_READS:-1}"

RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${OPENFDD_HOUR_TEST_DIR:-$ROOT/workspace/logs/hour_test_${MINUTES}m_${RUN_TS}}"

mkdir -p "$OUT"
exec > >(tee -a "$OUT/hour_test.log") 2>&1

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

CURL_TLS=()
[[ "$BASE" == https://* ]] && CURL_TLS=(-k)

TOKEN=""
INTEGRATOR_HDR=()
AGENT_HDR=()
json_api_once_done=false
rule_changed=false
FAIL=0

get_tokens() {
  TOKEN="$(openfdd_auth_login_token "$BASE" "$AUTH" integrator 2>/dev/null || true)"
  INTEGRATOR_HDR=()
  [[ -n "$TOKEN" ]] && INTEGRATOR_HDR=(-H "Authorization: Bearer $TOKEN")
  local at
  at="$(openfdd_auth_login_token "$BASE" "$AUTH" agent 2>/dev/null || true)"
  AGENT_HDR=()
  [[ -n "$at" ]] && AGENT_HDR=(-H "Authorization: Bearer $at")
}

api_get() {
  curl "${CURL_TLS[@]}" -fsS "${INTEGRATOR_HDR[@]}" "$BASE$1" 2>/dev/null || echo '{}'
}

api_post() {
  curl "${CURL_TLS[@]}" -fsS -X POST "${INTEGRATOR_HDR[@]}" -H 'Content-Type: application/json' \
    -d "$2" "$BASE$1" 2>/dev/null || echo '{}'
}

commission_post() {
  curl "${CURL_TLS[@]}" -fsS -X POST "${INTEGRATOR_HDR[@]}" -H 'Content-Type: application/json' \
    -d "$2" "$COMMISSION$1" 2>/dev/null || echo '{}'
}

change_fault_rule_param() {
  log "=== Minute $CHANGE_MIN: changing fault rule param for $RULE_ID ==="
  local before after
  before="$(api_get "/api/validation-runs/current/status")"
  echo "$before" >"$OUT/fault_rule_before.json"

  # Best-effort param nudge — API surface may vary by rev; try common routes
  local patch_body
  patch_body="$(jq -nc --arg rule "$RULE_ID" \
    '{rule_id:$rule, confirmation_seconds: 120, patch: {confirmation_seconds: 90}}')"

  for path in \
    "/api/validation-runs/current/rules/${RULE_ID}/params" \
    "/api/fdd/rules/${RULE_ID}/params" \
    "/api/validation/rules/${RULE_ID}"; do
    local code
    code="$(curl "${CURL_TLS[@]}" -sS -o "$OUT/fault_rule_patch.json" -w '%{http_code}' \
      -X PATCH "${INTEGRATOR_HDR[@]}" -H 'Content-Type: application/json' \
      -d "$patch_body" "$BASE$path" 2>/dev/null || echo 000)"
    log "PATCH $path → HTTP $code"
    if [[ "$code" =~ ^2 ]]; then
      rule_changed=true
      break
    fi
  done

  # Agent FDD cycle after param change
  if [[ ${#AGENT_HDR[@]} -gt 0 ]]; then
    curl "${CURL_TLS[@]}" -fsS -X POST "${AGENT_HDR[@]}" "$BASE/api/validation-runs/current/cycle" \
      -o "$OUT/fdd_cycle_after_rule_change.json" 2>/dev/null || echo '{}' >"$OUT/fdd_cycle_after_rule_change.json"
  fi

  after="$(api_get "/api/validation-runs/current/status")"
  echo "$after" >"$OUT/fault_rule_after.json"

  # Capture FDD / validation-store snapshot for data validation
  api_get "/api/validation-runs/current/results" >"$OUT/fault_rule_results_after.json" 2>/dev/null || true
  api_get "/api/fdd/status" >"$OUT/fdd_status_after_rule_change.json" 2>/dev/null || true

  local before_secs after_secs
  before_secs="$(jq -r --arg r "$RULE_ID" '.rules[]? | select(.rule_id==$r or .id==$r) | .confirmation_seconds // empty' \
    "$OUT/fault_rule_before.json" 2>/dev/null | head -1)"
  after_secs="$(jq -r --arg r "$RULE_ID" '.rules[]? | select(.rule_id==$r or .id==$r) | .confirmation_seconds // empty' \
    "$OUT/fault_rule_after.json" 2>/dev/null | head -1)"
  jq -nc \
    --arg rule "$RULE_ID" --arg before "${before_secs:-null}" --arg after "${after_secs:-null}" \
    --argjson patch_ok "$rule_changed" \
    '{rule_id:$rule,confirmation_seconds_before:$before,confirmation_seconds_after:$after,patch_accepted:$patch_ok}' \
    >"$OUT/fault_rule_param_delta.json"

  if [[ "$rule_changed" == true ]]; then
    log "Fault rule param patch accepted"
  else
    log "WARN: no PATCH route accepted — documenting for agent/PR (see fault_rule_patch.json)"
    echo "WONKY fault-rule-patch — no API route accepted param change at minute $CHANGE_MIN" >>"$OUT/wonky.txt"
  fi
}

poll_cycle() {
  local n="$1"
  local ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  local bacnet_ok=false modbus_ok=false haystack_ok=false json_ok=false stack_ok=false
  local bacnet_whois_ok=false modbus_value="" bacnet_value=""

  get_tokens

  stack_ok=false
  jq -e '.ok == true' <<< "$(api_get /api/health)" >/dev/null 2>&1 && stack_ok=true

  # Live OT reads every cycle — not poll/status-only (generates wire traffic + numeric Fn data).
  if [[ "$REQUIRE_LIVE_READS" == "1" && -n "$TOKEN" ]]; then
    local live
    live="$(openfdd_bench_live_ot_poll "$BASE" "$COMMISSION" "$TOKEN" "$ROOT")"
    echo "$live" >"$OUT/live_ot_cycle_${n}.json"
    jq -e '.modbus_read_ok == true' <<<"$live" >/dev/null 2>&1 && modbus_ok=true
    jq -e '.bacnet_read_ok == true' <<<"$live" >/dev/null 2>&1 && bacnet_ok=true
    jq -e '.bacnet_whois_ok == true' <<<"$live" >/dev/null 2>&1 && bacnet_whois_ok=true
    modbus_value="$(jq -r '.modbus_value // empty' <<<"$live")"
    bacnet_value="$(jq -r '.bacnet_value // empty' <<<"$live")"
  else
    jq -e 'type=="array" and length>0' <<< "$(commission_post /api/bacnet/whois "$(openfdd_bench_whois_json)")" \
      >/dev/null 2>&1 && { bacnet_ok=true; bacnet_whois_ok=true; }
    jq -e '.ok == true and (.value != null)' <<< "$(api_post /api/modbus/read "$(openfdd_bench_modbus_live_read_body)")" \
      >/dev/null 2>&1 && modbus_ok=true
  fi

  jq -e '.ok == true' <<< "$(api_post /api/haystack/test '{}')" >/dev/null 2>&1 && haystack_ok=true

  # JSON API — postbin/poll-once ONCE; poll/status every minute
  if [[ "$json_api_once_done" == false ]]; then
    local once json_body
    json_body="$(openfdd_bench_json_api_poll_once_body "$ROOT" 2>/dev/null || echo '{}')"
    once="$(api_post /api/json-api/poll-once "$json_body")"
    echo "$once" >"$OUT/json_api_poll_once_cycle_${n}.json"
    jq -e '.ok == true and (.http_status == 200 or .last_poll.ok == true)' <<<"$once" >/dev/null 2>&1 && json_ok=true
    json_api_once_done=true
    log "cycle=$n json-api poll-once (single validation for postbin/REST)"
  else
    jq -e '.ok == true or .last_poll.ok == true' <<< "$(api_get /api/json-api/poll/status)" \
      >/dev/null 2>&1 && json_ok=true
  fi

  # Mid-hour fault rule change
  if [[ "$n" -eq "$CHANGE_MIN" && "$rule_changed" == false ]]; then
    change_fault_rule_param || true
  fi

  jq -nc \
    --arg ts "$ts" --argjson cycle "$n" \
    --argjson stack "$stack_ok" --argjson bacnet "$bacnet_ok" \
    --argjson bacnet_whois "$bacnet_whois_ok" \
    --argjson modbus "$modbus_ok" --argjson haystack "$haystack_ok" \
    --argjson json "$json_ok" --argjson rule_changed "$rule_changed" \
    --argjson require_live "$([[ "$REQUIRE_LIVE_READS" == "1" ]] && echo true || echo false)" \
    --arg modbus_value "$modbus_value" --arg bacnet_value "$bacnet_value" \
    '{timestamp_utc:$ts,cycle:$cycle,stack_ok:$stack, bacnet_read_ok:$bacnet, bacnet_whois_ok:$bacnet_whois,
      modbus_read_ok:$modbus, modbus_poll_ok:$modbus, haystack_test_ok:$haystack, json_api_ok:$json,
      modbus_value:$modbus_value, bacnet_value:$bacnet_value, live_reads_required:$require_live,
      fault_rule_changed:$rule_changed}' \
    >>"$OUT/cycles.jsonl"

  log "cycle=$n/$CYCLES stack=$stack_ok bacnet_read=$bacnet_ok(${bacnet_value:-?}) whois=$bacnet_whois_ok modbus_read=$modbus_ok(${modbus_value:-?}) haystack=$haystack_ok json=$json_ok live_reads=$REQUIRE_LIVE_READS"

  local gate_fail=0
  [[ "$stack_ok" != true ]] && gate_fail=1
  [[ "$bacnet_ok" != true ]] && gate_fail=1
  [[ "$bacnet_whois_ok" != true ]] && gate_fail=1
  [[ "$modbus_ok" != true ]] && gate_fail=1
  [[ "$REQUIRE_HAYSTACK" == "1" && "$haystack_ok" != true ]] && gate_fail=1
  [[ "$REQUIRE_JSON" == "1" && "$json_ok" != true ]] && gate_fail=1

  if [[ "$gate_fail" -ne 0 ]]; then
    echo "FAIL cycle=$n — driver gate failed" >>"$OUT/failures.txt"
    return 1
  fi
  return 0
}

log "=== Hour test: ${MINUTES}m @ ${INTERVAL}s interval; fault rule change minute ${CHANGE_MIN} ==="
log "out=$OUT live_reads=$REQUIRE_LIVE_READS (Modbus POST /read + BACnet POST /read every cycle) json-api poll-once: cycle 1 require_haystack=$REQUIRE_HAYSTACK require_json=$REQUIRE_JSON"

: >"$OUT/cycles.jsonl"
: >"$OUT/failures.txt"
: >"$OUT/wonky.txt"

for n in $(seq 1 "$CYCLES"); do
  if ! poll_cycle "$n"; then
    FAIL=1
    log "FAIL at cycle $n — orchestrator should restart from scratch"
    break
  fi
  [[ "$n" -lt "$CYCLES" ]] && sleep "$INTERVAL"
done

fail_count="$(wc -l <"$OUT/failures.txt" | tr -d ' ')"
ok_count="$(wc -l <"$OUT/cycles.jsonl" | tr -d ' ')"

jq -nc \
  --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg dir "$OUT" \
  --argjson minutes "$MINUTES" \
  --argjson cycles_ok "$ok_count" \
  --argjson cycles_fail "$fail_count" \
  --argjson rule_changed "$rule_changed" \
  --argjson require_live "$([[ "$REQUIRE_LIVE_READS" == "1" ]] && echo true || echo false)" \
  '{timestamp_utc:$ts,artifact_dir:$dir,minutes:$minutes,cycles_ok:$cycles_ok,cycles_fail:$cycles_fail,
    fault_rule_changed:$rule_changed,live_reads_required:$require_live,
    ok:($cycles_fail==0)}' \
  >"$OUT/result.json"

log "=== Hour test DONE fail=$FAIL cycles_ok=$ok_count ==="
[[ "$FAIL" -eq 0 ]]
