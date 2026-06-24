#!/usr/bin/env bash
# Generic live FDD validation smoke — BACnet, Modbus, JSON API, historian, Docker.
#
# Example (6-hour live validation against a configured BACnet device):
#   OPENFDD_SMOKE_PROFILE=local_bacnet_fdd_validation \
#   OPENFDD_SMOKE_DEVICE_INSTANCE=5007 \
#   OPENFDD_SMOKE_DURATION_HOURS=6 \
#   OPENFDD_SMOKE_INTERVAL_SECONDS=300 \
#   OPENFDD_SMOKE_LIVE_FDD=1 \
#   OPENFDD_SMOKE_REQUIRE_CONFIRMED_FAULT=1 \
#   OPENFDD_SMOKE_VALIDATE_DOCKER=1 \
#   OPENFDD_SMOKE_VALIDATE_MODBUS=1 \
#   OPENFDD_SMOKE_VALIDATE_JSON_API=1 \
#   OPENFDD_SMOKE_JSON_API_MODE=postbin \
#   OPENFDD_SMOKE_NO_DEMO_PASS=1 \
#   ./scripts/smoke_live_fdd_validation.sh
#
# Short dry-run with safe simulation (no OT writes):
#   OPENFDD_SMOKE_DURATION_HOURS=0.05 OPENFDD_SMOKE_INTERVAL_SECONDS=30 \
#   OPENFDD_SMOKE_SIMULATE=1 OPENFDD_SMOKE_SAMPLES=3 \
#   ./scripts/smoke_live_fdd_validation.sh
#
# Finalize a crashed run from existing summary.jsonl:
#   OPENFDD_SMOKE_FINALIZE_ONLY=1 \
#   OPENFDD_SMOKE_ARTIFACT_DIR=workspace/logs/live_fdd_validation_6h_... \
#   OPENFDD_SMOKE_SIMULATE=1 OPENFDD_SMOKE_REQUIRE_CONFIRMED_FAULT=1 \
#   ./scripts/smoke_live_fdd_validation.sh
#
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_rust_site_lib.sh
source "$ROOT/scripts/openfdd_rust_site_lib.sh"
# shellcheck source=scripts/openfdd_auth_lib.sh
source "$ROOT/scripts/openfdd_auth_lib.sh"
# shellcheck source=scripts/openfdd_csv_append_validation.sh
source "$ROOT/scripts/openfdd_csv_append_validation.sh"

BASE="${OPENFDD_API_BASE:-http://127.0.0.1:8080}"
CURL_TLS=()
if [[ "$BASE" == https://* ]]; then
  CURL_TLS=(-k)
fi

PROFILE="${OPENFDD_SMOKE_PROFILE:-local_bacnet_fdd_validation}"
DEVICE_INSTANCE="${OPENFDD_SMOKE_DEVICE_INSTANCE:-0}"
HOURS="${OPENFDD_SMOKE_DURATION_HOURS:-${BENCH_SMOKE_HOURS:-6}}"
INTERVAL="${OPENFDD_SMOKE_INTERVAL_SECONDS:-${BENCH_SMOKE_INTERVAL_SEC:-300}}"
SAMPLES="${OPENFDD_SMOKE_SAMPLES:-${BENCH_SMOKE_SAMPLES:-}}"
LIVE_FDD="${OPENFDD_SMOKE_LIVE_FDD:-${BENCH_SMOKE_LIVE_FDD:-0}}"
SIMULATE="${OPENFDD_SMOKE_SIMULATE:-${BENCH_SMOKE_SIMULATE:-0}}"
REQUIRE_CONFIRMED="${OPENFDD_SMOKE_REQUIRE_CONFIRMED_FAULT:-0}"
REQUIRE_MODBUS="${OPENFDD_SMOKE_REQUIRE_MODBUS:-0}"
VALIDATE_DOCKER="${OPENFDD_SMOKE_VALIDATE_DOCKER:-1}"
VALIDATE_MODBUS="${OPENFDD_SMOKE_VALIDATE_MODBUS:-1}"
VALIDATE_JSON="${OPENFDD_SMOKE_VALIDATE_JSON_API:-1}"
CSV_APPEND="${OPENFDD_SMOKE_CSV_APPEND:-1}"
JSON_API_URL="${OPENFDD_SMOKE_JSON_API_URL:-https://httpbin.org/get}"
NO_DEMO_PASS="${OPENFDD_SMOKE_NO_DEMO_PASS:-0}"
SHORT_FDD="${BENCH_SMOKE_SHORT_FDD:-0}"
DURATION_MIN="${BENCH_SMOKE_DURATION_MINUTES:-30}"

RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
ARTIFACT_ROOT="${OPENFDD_SMOKE_ARTIFACT_DIR:-$ROOT/workspace/logs/live_fdd_validation_${RUN_TS}}"
LOG_DIR="$ARTIFACT_ROOT"
AUTH="$ROOT/workspace/auth.env.local"

export OPENFDD_SMOKE_PROFILE="$PROFILE"
export OPENFDD_HISTORIAN_SUBDIR="${OPENFDD_HISTORIAN_SUBDIR:-validation}"
if [[ "$DEVICE_INSTANCE" != "0" ]]; then
  export OPENFDD_SMOKE_DEVICE_INSTANCE="$DEVICE_INSTANCE"
fi
export OPENFDD_SMOKE_LIVE_FDD="$LIVE_FDD"
export OPENFDD_SMOKE_JSON_API_URL="$JSON_API_URL"

mkdir -p "$LOG_DIR"

capture_docker_state() {
  local tag="$1"
  if [[ "$VALIDATE_DOCKER" != "1" ]]; then return 0; fi
  docker compose ps >"$LOG_DIR/docker_compose_ps_${tag}.txt" 2>&1 || true
  docker ps >"$LOG_DIR/docker_ps_${tag}.txt" 2>&1 || true
}

classify_docker_logs() {
  local since="$1" out="$2"
  docker compose logs --since "$since" 2>&1 | tee "$out" | grep -Ei 'panic|fatal|stack trace|corruption|Arrow.*fail|DataFusion.*fail' || true
}

infer_proof_flags_from_artifacts() {
  local latest_cycle
  latest_cycle="$(ls -1 "$LOG_DIR"/capture_*_fdd_cycle.json 2>/dev/null | sort | tail -1 || true)"
  if [[ -n "$latest_cycle" && -f "$latest_cycle" ]]; then
    LIVE_FDD_PASS="$(jq -r '.proof.live_fdd_pass // false' "$latest_cycle")"
    DEMO_ONLY="$(jq -r 'if .proof.demo_only == null then true else .proof.demo_only end' "$latest_cycle")"
    [[ "$LIVE_FDD_PASS" == "true" ]] && LIVE_FDD_PASS=true || LIVE_FDD_PASS=false
    [[ "$DEMO_ONLY" == "false" ]] && DEMO_ONLY=false || DEMO_ONLY=true
  fi
  if [[ -f "$LOG_DIR/summary.jsonl" ]]; then
    SEEN_RAW_FAULT="$(jq -s 'any(.[]; (.raw_fault_count // 0) > 0)' "$LOG_DIR/summary.jsonl")"
    SEEN_CONFIRMED="$(jq -s 'any(.[]; (.confirmed_fault_count // 0) > 0)' "$LOG_DIR/summary.jsonl")"
    SEEN_CLEAR="$(jq -s 'any(.[]; (.expected_phase // "") == "clear" or (.expected_phase // "") == "normal")' "$LOG_DIR/summary.jsonl")"
  fi
}

write_final_report() {
  infer_proof_flags_from_artifacts

  fail_count="$(jq -s '[.[] | select(.api_health_ok==false or .fdd_sql_ok==false)] | length' "$LOG_DIR/summary.jsonl" 2>/dev/null || echo 0)"
  total="$(wc -l <"$LOG_DIR/summary.jsonl" | tr -d ' ')"

  jq -nc \
    --arg finished "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --argjson samples "$total" \
    --argjson failures "$fail_count" \
    --argjson live_pass "$LIVE_FDD_PASS" \
    --argjson demo_only "$DEMO_ONLY" \
    --argjson seen_raw "$SEEN_RAW_FAULT" \
    --argjson seen_confirmed "$SEEN_CONFIRMED" \
    --argjson seen_clear "$SEEN_CLEAR" \
    --arg artifact "$LOG_DIR" \
    --arg report_pdf "$LOG_DIR/validation_report.pdf" \
    --argjson csv_before "${CSV_APPEND_HIST_ROWS_BEFORE:-0}" \
    '{finished_at:$finished,samples:$samples,interval_failures:$failures,live_fdd_pass:$live_pass,demo_only:$demo_only,seen_raw_fault:$seen_raw,seen_confirmed_fault:$seen_confirmed,seen_clear:$seen_clear,artifact_dir:$artifact,validation_report_pdf:$report_pdf,csv_hist_rows_before:$csv_before}' \
    >"$LOG_DIR/final_report.json"

  {
    echo "# Live FDD Validation Report"
    echo ""
    echo "- Artifact directory: \`$LOG_DIR\`"
    echo "- Samples: $total"
    echo "- Interval failures: $fail_count"
    echo "- Live FDD pass: $LIVE_FDD_PASS"
    echo "- Demo only: $DEMO_ONLY"
    echo "- Raw fault seen: $SEEN_RAW_FAULT"
    echo "- Confirmed fault seen: $SEEN_CONFIRMED"
    echo "- Clear seen: $SEEN_CLEAR"
  } >"$LOG_DIR/final_report.md"
}

evaluate_pass_fail() {
  local fail_count="$1"
  if [[ "$NO_DEMO_PASS" == "1" && "$DEMO_ONLY" == "true" && "$SIMULATE" != "1" ]]; then
    echo "FAIL: ended DEMO ONLY while OPENFDD_SMOKE_NO_DEMO_PASS=1" | tee -a "$LOG_DIR/run.log" >&2
    return 1
  fi

  if [[ "$REQUIRE_CONFIRMED" == "1" ]]; then
    if [[ "$SIMULATE" == "1" && "$LIVE_FDD_PASS" != "true" ]]; then
      echo "FAIL: simulation did not prove confirmed fault transitions" | tee -a "$LOG_DIR/run.log" >&2
      return 1
    fi
    if [[ "$SIMULATE" != "1" && ( "$SEEN_RAW_FAULT" != "true" || "$SEEN_CONFIRMED" != "true" || "$SEEN_CLEAR" != "true" ) ]]; then
      echo "FAIL: live run missing raw/confirmed/clear transitions — inspect summary.jsonl" | tee -a "$LOG_DIR/run.log" >&2
      return 1
    fi
  fi

  if [[ "$REQUIRE_MODBUS" == "1" ]]; then
    local modbus_fails
    modbus_fails="$(jq -s '[.[] | select(.modbus_ok==false)] | length' "$LOG_DIR/summary.jsonl")"
    if [[ "$modbus_fails" -gt 0 ]]; then
      echo "FAIL: Modbus required but offline/degraded" | tee -a "$LOG_DIR/run.log" >&2
      return 1
    fi
  fi

  if [[ "$fail_count" -gt 0 ]]; then
    echo "FAIL: some intervals failed — inspect $LOG_DIR/summary.jsonl" >&2
    return 1
  fi

  echo "PASS: live FDD validation smoke complete." | tee -a "$LOG_DIR/run.log"
  return 0
}

should_stop_sampling() {
  local sample_n="$1"
  local remaining="$2"
  if [[ -n "$SAMPLES" && "$sample_n" -ge "$SAMPLES" ]]; then
    return 0
  fi
  if [[ "$SHORT_FDD" == "1" && "$remaining" -le 0 ]]; then
    return 0
  fi
  if [[ "$SHORT_FDD" != "1" && -z "$SAMPLES" && "$remaining" -le 0 ]]; then
    return 0
  fi
  return 1
}

sleep_until_next_sample() {
  local remaining="$1"
  if should_stop_sampling "$sample_n" "$remaining"; then
    return 0
  fi
  local sleep_for="$INTERVAL"
  if [[ "$SHORT_FDD" != "1" && -z "$SAMPLES" && "$remaining" -lt "$sleep_for" ]]; then
    sleep_for="$remaining"
  fi
  if (( sleep_for > 0 )); then
    sleep "$sleep_for"
  fi
}

if [[ "${OPENFDD_SMOKE_FINALIZE_ONLY:-0}" == "1" ]]; then
  LOG_DIR="${OPENFDD_SMOKE_ARTIFACT_DIR:-$ARTIFACT_ROOT}"
  if [[ ! -f "$LOG_DIR/summary.jsonl" ]]; then
    echo "ERROR: missing $LOG_DIR/summary.jsonl" >&2
    exit 1
  fi
  LIVE_FDD_PASS=false
  DEMO_ONLY=true
  SEEN_RAW_FAULT=false
  SEEN_CONFIRMED=false
  SEEN_CLEAR=false
  capture_docker_state end
  write_final_report
  fail_count="$(jq -s '[.[] | select(.api_health_ok==false or .fdd_sql_ok==false)] | length' "$LOG_DIR/summary.jsonl" 2>/dev/null || echo 0)"
  echo "Finalized: $(date -Iseconds)" | tee -a "$LOG_DIR/run.log"
  evaluate_pass_fail "$fail_count"
  exit $?
fi

if [[ "$VALIDATE_DOCKER" == "1" ]]; then
  openfdd_rust_check_docker
fi

if [[ ! -f "$AUTH" ]]; then
  echo "ERROR: missing $AUTH — run bootstrap or auth init first" >&2
  exit 1
fi

INTEGRATOR_PW="$(openfdd_auth_plaintext_password "$AUTH" integrator)" || exit 1
AGENT_PW="$(openfdd_auth_plaintext_password "$AUTH" agent)" || exit 1

login() {
  local user="$1" pw="$2"
  curl "${CURL_TLS[@]}" -fsS -X POST "${BASE}/api/auth/login" \
    -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg u "$user" --arg p "$pw" '{username:$u,password:$p}')" \
    | jq -r '.token // .access_token'
}

INT_TOKEN="$(login integrator "$INTEGRATOR_PW")"
AGENT_TOKEN="$(login agent "$AGENT_PW")"

if [[ "$CSV_APPEND" == "1" ]]; then
  openfdd_csv_append_init "$LOG_DIR"
  CSV_APPEND_HIST_ROWS_BEFORE="$(openfdd_csv_append_hist_rows "$BASE" "$INT_TOKEN")"
fi

if [[ "$SHORT_FDD" == "1" ]]; then
  INTERVAL="${OPENFDD_SMOKE_INTERVAL_SECONDS:-60}"
  END=$(( $(date +%s) + DURATION_MIN * 60 ))
  MODE_LABEL="short-fdd-${DURATION_MIN}m"
else
  if [[ -n "$SAMPLES" ]]; then
    END=0
  else
    END=$(( $(date +%s) + $(python3 - <<PY
h=float("$HOURS")
print(int(h*3600))
PY
) ))
  fi
  MODE_LABEL="live-fdd-validation-${HOURS}h"
fi

jq -nc \
  --arg profile "$PROFILE" \
  --arg device "$DEVICE_INSTANCE" \
  --arg base "$BASE" \
  --argjson interval "$INTERVAL" \
  --argjson hours "$HOURS" \
  --arg json_url "$JSON_API_URL" \
  --arg mode "$MODE_LABEL" \
  --arg artifact "$LOG_DIR" \
  '{profile_id:$profile,device_instance:($device|tonumber?),interval_seconds:$interval,duration_hours:($hours|tonumber?),json_api_url:$json_url,mode:$mode,artifact_dir:$artifact,started_at:(now|todate)}' \
  >"$LOG_DIR/run_config.json"

echo "Live FDD validation mode=$MODE_LABEL interval=${INTERVAL}s artifact=$LOG_DIR device=$DEVICE_INSTANCE simulate=$SIMULATE csv_append=$CSV_APPEND" | tee "$LOG_DIR/run.log"
echo "Started: $(date -Iseconds)" | tee -a "$LOG_DIR/run.log"

VALIDATION_STARTED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

capture_docker_state start
LAST_DOCKER_SINCE="1m"

if [[ "$SIMULATE" == "1" ]]; then
  echo "Injecting simulation scenario (5m normal / 6m fault / 5m clear)..." | tee -a "$LOG_DIR/run.log"
  curl "${CURL_TLS[@]}" -fsS -X POST "${BASE}/api/validation-runs/current/inject-scenario" \
    -H "Authorization: Bearer $AGENT_TOKEN" \
    -H 'Content-Type: application/json' \
    -d '{"normal_minutes":5,"fault_minutes":6,"clear_minutes":5}' \
    | tee "$LOG_DIR/inject_scenario.json" >/dev/null
fi

expected_phase_for_sample() {
  local n="$1"
  if [[ "$SIMULATE" != "1" ]]; then
    echo "live"
    return
  fi
  # 72 samples @ 5min ≈ 6h: baseline, fault+sustain, clear, optional 2nd fault cycle
  if [[ "$n" -le 12 ]]; then echo "normal"
  elif [[ "$n" -le 36 ]]; then echo "fault"
  elif [[ "$n" -le 48 ]]; then echo "clear"
  elif [[ "$n" -le 60 ]]; then echo "fault"
  else echo "clear"
  fi
}

sample_n=0
LIVE_FDD_PASS=false
DEMO_ONLY=true
SEEN_RAW_FAULT=false
SEEN_CONFIRMED=false
SEEN_CLEAR=false

while true; do
  sample_n=$((sample_n + 1))
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  prefix="${LOG_DIR}/capture_${ts//:/-}"
  phase="$(expected_phase_for_sample "$sample_n")"

  api_health_ok=false
  stack_health_ok=false
  docker_ok=true
  docker_error_count=0
  bacnet_device_seen=false
  bacnet_poll_ok=false
  historian_rows_written=0
  fdd_sql_ok=false
  raw_fault_count=0
  confirmed_fault_count=0
  minutes_in_fault=0
  confirmation_required_minutes=5
  modbus_ok=false
  modbus_registers_read=0
  json_api_ok=false
  json_api_points_read=0
  csv_import_ok=true
  csv_hist_delta=0
  override_scan_ok=false
  err_msg=""
  data_source="unknown"
  demo_only=true
  live_pass=false
  source_id="source:validation"

  if curl "${CURL_TLS[@]}" -fsS "${BASE}/health" >/dev/null 2>&1 \
    && curl "${CURL_TLS[@]}" -fsS "${BASE}/api/health" >/dev/null 2>&1; then
    api_health_ok=true
  fi

  if curl "${CURL_TLS[@]}" -fsS "${BASE}/api/health/stack" \
    -H "Authorization: Bearer $INT_TOKEN" \
    -o "${prefix}_stack_health.json" 2>/dev/null; then
    jq -e '.ok == true' "${prefix}_stack_health.json" >/dev/null 2>&1 && stack_health_ok=true
  fi

  if [[ "$VALIDATE_DOCKER" == "1" ]]; then
    capture_docker_state "sample_${sample_n}"
    serious="$(classify_docker_logs "$LAST_DOCKER_SINCE" "${prefix}_docker_logs.txt" | wc -l | tr -d ' ')"
    docker_error_count="$serious"
    [[ "$serious" -eq 0 ]] || docker_ok=false
    LAST_DOCKER_SINCE="${INTERVAL}s"
  fi

  if curl "${CURL_TLS[@]}" -fsS "${BASE}/api/bacnet/driver/tree" \
    -H "Authorization: Bearer $INT_TOKEN" \
    -o "${prefix}_tree.json" 2>/dev/null; then
    if [[ "$DEVICE_INSTANCE" != "0" ]]; then
      if jq -e --argjson inst "$DEVICE_INSTANCE" '
        ([.. | objects | .device_instance? // .instance? // empty] | map(tostring) | index($inst|tostring)) != null
        or ([.. | strings] | any(test("device[:=]" + ($inst|tostring)) or test(":analog-input:")))
      ' "${prefix}_tree.json" >/dev/null 2>&1; then
        bacnet_device_seen=true
      fi
    else
      jq -e '((.drivers // []) | length >= 1) or ((.devices // []) | length >= 1)' "${prefix}_tree.json" >/dev/null 2>&1 && bacnet_device_seen=true
    fi
  fi

  if [[ "$VALIDATE_MODBUS" == "1" ]]; then
    modbus_body='{"register":30001,"function":"input_register","scale":0.1,"unit":"degF"}'
    if curl "${CURL_TLS[@]}" -fsS -X POST "${BASE}/api/modbus/read" \
      -H "Authorization: Bearer $INT_TOKEN" \
      -H 'Content-Type: application/json' \
      -d "$modbus_body" \
      -o "${prefix}_modbus.json" 2>/dev/null; then
      if jq -e '.value != null or .ok == true' "${prefix}_modbus.json" >/dev/null 2>&1; then
        modbus_ok=true
        modbus_registers_read=1
      fi
    fi
  else
    modbus_ok=true
  fi

  if [[ "$VALIDATE_JSON" == "1" ]]; then
    if curl "${CURL_TLS[@]}" -fsS -X POST "${BASE}/api/json-api/poll-once" \
      -H "Authorization: Bearer $INT_TOKEN" \
      -H 'Content-Type: application/json' \
      -d "$(jq -nc --arg url "$JSON_API_URL" '{url:$url}')" \
      -o "${prefix}_json_api.json" 2>/dev/null; then
      json_api_points_read="$(jq -r '.parsed_points_count // (.points|length) // 0' "${prefix}_json_api.json")"
      jq -e '.ok == true' "${prefix}_json_api.json" >/dev/null 2>&1 && json_api_ok=true
    fi
  else
    json_api_ok=true
  fi

  if [[ "$CSV_APPEND" == "1" ]]; then
    csv_interval="${OPENFDD_SMOKE_CSV_INTERVAL_SECONDS:-300}"
    if (( sample_n == 1 || (INTERVAL > 0 && (sample_n * INTERVAL) % csv_interval == 0) )); then
      hist_before="$(openfdd_csv_append_hist_rows "$BASE" "$INT_TOKEN")"
      if openfdd_csv_append_import_batch "$BASE" "$INT_TOKEN" "$ts" "$phase" "$sample_n"; then
        hist_after="$(openfdd_csv_append_hist_rows "$BASE" "$INT_TOKEN")"
        csv_hist_delta=$(( hist_after - hist_before ))
        [[ "$csv_hist_delta" -ge 0 ]] || csv_import_ok=false
      else
        csv_import_ok=false
      fi
    fi
  fi

  cycle_body='{}'
  if [[ "$phase" != "live" ]]; then
    cycle_body="$(jq -nc --arg p "$phase" '{simulation_phase:$p}')"
  fi

  if curl "${CURL_TLS[@]}" -fsS -X POST "${BASE}/api/validation-runs/current/cycle" \
    -H "Authorization: Bearer $AGENT_TOKEN" \
    -H 'Content-Type: application/json' \
    -d "$cycle_body" \
    -o "${prefix}_fdd_cycle.json" 2>/dev/null; then
    fdd_sql_ok=true
    jq -e '.ok == true' "${prefix}_fdd_cycle.json" >/dev/null 2>&1 || fdd_sql_ok=false
    data_source="$(jq -r '.fdd_eval.data_source // .capture.data_source // "unknown"' "${prefix}_fdd_cycle.json")"
    demo_only="$(jq -r 'if .proof.demo_only == null then true else .proof.demo_only end' "${prefix}_fdd_cycle.json")"
    raw_fault_count="$(jq -r '.proof.raw_fault_samples // 0' "${prefix}_fdd_cycle.json")"
    confirmed_fault_count="$(jq -r '.proof.confirmed_fault_samples // (.proof.confirmed_fault_count // 0)' "${prefix}_fdd_cycle.json")"
    confirmation_required_minutes="$(jq -r '.proof.confirmation_required_minutes // 5' "${prefix}_fdd_cycle.json")"
    minutes_in_fault="$(jq -r '.fdd_eval.rows[-1].minutes_in_fault // 0' "${prefix}_fdd_cycle.json")"
    historian_rows_written="$(jq -r '.capture.historian_rows_written // 0' "${prefix}_fdd_cycle.json")"
    live_pass="$(jq -r '.proof.live_fdd_pass // false' "${prefix}_fdd_cycle.json")"
    source_id="$(jq -r '.capture.row.source // "source:validation"' "${prefix}_fdd_cycle.json")"
    [[ "$live_pass" == "true" ]] && LIVE_FDD_PASS=true
    [[ "$demo_only" == "false" ]] && DEMO_ONLY=false
    [[ "$raw_fault_count" -gt 0 ]] && SEEN_RAW_FAULT=true
    [[ "$confirmed_fault_count" -gt 0 ]] && SEEN_CONFIRMED=true
    if [[ "$phase" == "clear" || "$phase" == "normal" ]] && [[ "$raw_fault_count" -eq 0 ]]; then
      SEEN_CLEAR=true
    fi
    bacnet_poll_ok="$(jq -r '.capture.ok // false' "${prefix}_fdd_cycle.json")"
    cp "${prefix}_fdd_cycle.json" "${prefix}_fdd.json"
  else
    err_msg="fdd cycle failed"
    fdd_sql_ok=false
  fi

  if curl "${CURL_TLS[@]}" -fsS "${BASE}/api/historian/validation/status" \
    -H "Authorization: Bearer $INT_TOKEN" \
    -o "${prefix}_historian.json" 2>/dev/null; then
    jq -e '.row_count >= 0' "${prefix}_historian.json" >/dev/null 2>&1 || err_msg="${err_msg}; historian status invalid"
  fi

  if [[ -f "$ROOT/workspace/overrides/last_scan.json" ]]; then
    override_scan_ok=true
  fi

  expected_fault_state="no_fault"
  actual_fault_state="no_fault"
  if [[ "$phase" == "fault" ]]; then expected_fault_state="raw_fault"; fi
  if [[ "$raw_fault_count" -gt 0 ]]; then actual_fault_state="raw_fault"; fi
  if [[ "$confirmed_fault_count" -gt 0 ]]; then actual_fault_state="confirmed_fault"; fi

  jq -nc \
    --arg ts "$ts" \
    --arg mode "$MODE_LABEL" \
    --arg data_source "$data_source" \
    --arg phase "$phase" \
    --arg source_id "$source_id" \
    --arg err "$err_msg" \
    --arg expected_fault "$expected_fault_state" \
    --arg actual_fault "$actual_fault_state" \
    --argjson n "$sample_n" \
    --argjson device "$DEVICE_INSTANCE" \
    --argjson api_health "$api_health_ok" \
    --argjson stack_health "$stack_health_ok" \
    --argjson docker_ok "$docker_ok" \
    --argjson docker_errors "$docker_error_count" \
    --argjson bacnet_seen "$bacnet_device_seen" \
    --argjson bacnet_poll "$bacnet_poll_ok" \
    --argjson hist_rows "$historian_rows_written" \
    --argjson fdd_ok "$fdd_sql_ok" \
    --argjson raw_fault "$raw_fault_count" \
    --argjson confirmed_fault "$confirmed_fault_count" \
    --argjson minutes_fault "$minutes_in_fault" \
    --argjson confirm_min "$confirmation_required_minutes" \
    --argjson modbus "$modbus_ok" \
    --argjson modbus_regs "$modbus_registers_read" \
    --argjson json_ok "$json_api_ok" \
    --argjson json_pts "$json_api_points_read" \
    --argjson csv_ok "$csv_import_ok" \
    --argjson csv_hist_delta "$csv_hist_delta" \
    --argjson override_ok "$override_scan_ok" \
    --argjson demo_only "$demo_only" \
    '{timestamp_utc:$ts,sample_index:$n,mode:$mode,api_health_ok:$api_health,stack_health_ok:$stack_health,docker_ok:$docker_ok,docker_error_count:$docker_errors,source_id:$source_id,smoke_device_instance:$device,bacnet_device_seen:$bacnet_seen,bacnet_poll_ok:$bacnet_poll,historian_rows_written:$hist_rows,fdd_sql_ok:$fdd_ok,raw_fault_count:$raw_fault,confirmed_fault_count:$confirmed_fault,minutes_in_fault:$minutes_fault,confirmation_required_minutes:$confirm_min,expected_phase:$phase,expected_fault_state:$expected_fault,actual_fault_state:$actual_fault,demo_only:$demo_only,modbus_ok:$modbus,modbus_registers_read:$modbus_regs,json_api_ok:$json_ok,json_api_points_read:$json_pts,csv_import_ok:$csv_ok,csv_hist_row_delta:$csv_hist_delta,override_scan_ok:$override_ok,data_source:$data_source,error:$err}' \
    >>"$LOG_DIR/summary.jsonl"

  echo "[$ts] sample=$sample_n phase=$phase api=$api_health_ok stack=$stack_health_ok docker=$docker_ok bacnet=$bacnet_device_seen fdd=$fdd_sql_ok modbus=$modbus_ok json=$json_api_ok source=$data_source demo=$demo_only raw=$raw_fault_count confirmed=$confirmed_fault_count"

  remaining=$(( END - $(date +%s) ))
  if should_stop_sampling "$sample_n" "$remaining"; then
    break
  fi
  sleep_until_next_sample "$remaining"
done

capture_docker_state end

curl "${CURL_TLS[@]}" -fsS "${BASE}/api/validation-runs/current/status" \
  -H "Authorization: Bearer $INT_TOKEN" \
  -o "$LOG_DIR/final_status.json" 2>/dev/null || true

VALIDATION_FINISHED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

if [[ "$CSV_APPEND" == "1" ]]; then
  openfdd_csv_append_export_checks "$BASE" "$INT_TOKEN" before_purge || true
  openfdd_csv_append_purge_validation "$BASE" "$INT_TOKEN" "$VALIDATION_STARTED" "$VALIDATION_FINISHED" || true
  openfdd_csv_append_export_checks "$BASE" "$INT_TOKEN" after_purge || true
fi

report_draft="$(curl "${CURL_TLS[@]}" -fsS -X POST "${BASE}/api/reports/draft" \
  -H "Authorization: Bearer $INT_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"template_id":"validation-summary","title":"Live FDD Validation Report"}' 2>/dev/null || echo '{}')"
echo "$report_draft" >"$LOG_DIR/validation_report_draft.json"
report_id="$(jq -r '.report_id // empty' <<<"$report_draft")"
if [[ -n "$report_id" ]]; then
  curl "${CURL_TLS[@]}" -fsS -X POST "${BASE}/api/reports/${report_id}/render/pdf" \
    -H "Authorization: Bearer $INT_TOKEN" \
    -H 'Content-Type: application/json' \
    -d '{}' -o "$LOG_DIR/validation_report_render.json" 2>/dev/null || true
  curl "${CURL_TLS[@]}" -fsS "${BASE}/api/reports/${report_id}/download.pdf" \
    -H "Authorization: Bearer $INT_TOKEN" \
    -o "$LOG_DIR/validation_report.pdf" 2>/dev/null || true
fi

write_final_report
fail_count="$(jq -s '[.[] | select(.api_health_ok==false or .fdd_sql_ok==false)] | length' "$LOG_DIR/summary.jsonl" 2>/dev/null || echo 0)"
total="$(wc -l <"$LOG_DIR/summary.jsonl" | tr -d ' ')"

echo "Finished: $(date -Iseconds)" | tee -a "$LOG_DIR/run.log"
echo "Samples: $total interval_failures: $fail_count artifact=$LOG_DIR" | tee -a "$LOG_DIR/run.log"

evaluate_pass_fail "$fail_count"
exit $?
