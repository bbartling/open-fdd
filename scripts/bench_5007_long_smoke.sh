#!/usr/bin/env bash
# Bench device 5007 smoke — long stability OR short live-FDD proof.
#
# Long stability (default, 6h/8h API + polling):
#   BENCH_SMOKE_HOURS=6 ./scripts/bench_5007_long_smoke.sh
#   BENCH_SMOKE_HOURS=8 BENCH_SMOKE_INTERVAL_SEC=300 ./scripts/bench_5007_long_smoke.sh
#
# Short live-FDD proof (~30 min, 60s BACnet scrape + historian + DataFusion):
#   BENCH_SMOKE_SHORT_FDD=1 \
#   BENCH_SMOKE_DURATION_MINUTES=30 \
#   BENCH_SMOKE_INTERVAL_SECONDS=60 \
#   BENCH_SMOKE_LIVE_FDD=1 \
#   ./scripts/bench_5007_long_smoke.sh
#
# Safe simulation proof (no OT writes — injects historian rows):
#   BENCH_SMOKE_SHORT_FDD=1 BENCH_SMOKE_SIMULATE=1 ./scripts/bench_5007_long_smoke.sh
#
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_rust_site_lib.sh
source "$ROOT/scripts/openfdd_rust_site_lib.sh"

BASE="${OPENFDD_API_BASE:-http://127.0.0.1:8080}"
CURL_TLS=()
if [[ "$BASE" == https://* ]]; then
  CURL_TLS=(-k)
fi

SHORT_FDD="${BENCH_SMOKE_SHORT_FDD:-0}"
SIMULATE="${BENCH_SMOKE_SIMULATE:-0}"
LIVE_FDD="${BENCH_SMOKE_LIVE_FDD:-0}"
HOURS="${BENCH_SMOKE_HOURS:-6}"
INTERVAL="${BENCH_SMOKE_INTERVAL_SEC:-${BENCH_SMOKE_INTERVAL_SECONDS:-300}}"
DURATION_MIN="${BENCH_SMOKE_DURATION_MINUTES:-30}"
SAMPLES="${BENCH_SMOKE_SAMPLES:-}"
LOG_DIR="${BENCH_SMOKE_LOG_DIR:-$ROOT/workspace/logs/bench_5007_smoke}"
AUTH="$ROOT/workspace/auth.env.local"

if [[ "$SHORT_FDD" == "1" ]]; then
  INTERVAL="${BENCH_SMOKE_INTERVAL_SECONDS:-60}"
  END=$(( $(date +%s) + DURATION_MIN * 60 ))
  MODE_LABEL="short-fdd-${DURATION_MIN}m"
else
  if [[ -n "$SAMPLES" ]]; then
    END=0
  else
    END=$(( $(date +%s) + HOURS * 3600 ))
  fi
  MODE_LABEL="long-stability-${HOURS}h"
fi

mkdir -p "$LOG_DIR"
openfdd_rust_check_docker

if [[ ! -f "$AUTH" ]]; then
  echo "ERROR: missing $AUTH — run bootstrap or auth init first" >&2
  exit 1
fi

INTEGRATOR_PW="$(grep '^OFDD_INTEGRATOR_PASSWORD=' "$AUTH" | cut -d= -f2- | tr -d '\r')"
AGENT_PW="$(grep '^OFDD_AGENT_PASSWORD=' "$AUTH" | cut -d= -f2- | tr -d '\r')"

login() {
  local user="$1" pw="$2"
  curl "${CURL_TLS[@]}" -fsS -X POST "${BASE}/api/auth/login" \
    -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg u "$user" --arg p "$pw" '{username:$u,password:$p}')" \
    | jq -r '.token // .access_token'
}

INT_TOKEN="$(login integrator "$INTEGRATOR_PW")"
AGENT_TOKEN="$(login agent "$AGENT_PW")"

echo "Bench 5007 smoke mode=$MODE_LABEL interval=${INTERVAL}s log=$LOG_DIR live_fdd=$LIVE_FDD simulate=$SIMULATE"
echo "Started: $(date -Iseconds)" | tee -a "$LOG_DIR/run.log"

if [[ "$SHORT_FDD" == "1" && "$SIMULATE" == "1" ]]; then
  echo "Injecting simulation scenario (5m normal / 6m fault / 5m clear)..." | tee -a "$LOG_DIR/run.log"
  curl "${CURL_TLS[@]}" -fsS -X POST "${BASE}/api/bench/5007/smoke/inject-scenario" \
    -H "Authorization: Bearer $AGENT_TOKEN" \
    -H 'Content-Type: application/json' \
    -d '{"normal_minutes":5,"fault_minutes":6,"clear_minutes":5}' \
    | tee "$LOG_DIR/inject_scenario.json" >/dev/null
fi

simulation_phase_for_sample() {
  local n="$1"
  if [[ "$SIMULATE" != "1" ]]; then
    echo ""
    return
  fi
  # 30 samples @ 60s: 0-4 normal, 5-10 fault, 11+ clear
  if [[ "$n" -le 5 ]]; then echo "normal"
  elif [[ "$n" -le 11 ]]; then echo "fault"
  else echo "clear"
  fi
}

sample_n=0
LIVE_FDD_PASS=false
DEMO_ONLY=true

while true; do
  sample_n=$((sample_n + 1))
  ts="$(date -Iseconds)"
  prefix="${LOG_DIR}/capture_${ts//:/-}"
  phase="$(simulation_phase_for_sample "$sample_n")"

  health_ok=false
  tree_ok=false
  modbus_ok=false
  json_api_ok=false
  historian_ok=false
  fdd_ok=false
  live_pass=false
  demo_only=true
  raw_fault_count=0
  confirmed_fault_count=0
  data_source="unknown"

  if curl "${CURL_TLS[@]}" -fsS "${BASE}/api/health" >/dev/null 2>&1; then
    health_ok=true
  fi

  if curl "${CURL_TLS[@]}" -fsS "${BASE}/api/bacnet/driver/tree" \
    -H "Authorization: Bearer $INT_TOKEN" \
    -o "${prefix}_tree.json" 2>/dev/null; then
    tree_ok=true
    jq -e '((.drivers // []) | length >= 1) or ((.devices // []) | length >= 1)' "${prefix}_tree.json" >/dev/null 2>&1 || tree_ok=false
  fi

  if curl "${CURL_TLS[@]}" -fsS -X POST "${BASE}/api/modbus/read" \
    -H "Authorization: Bearer $INT_TOKEN" \
    -H 'Content-Type: application/json' \
    -d '{"register":30001,"function":"input_register","scale":0.1,"unit":"degF"}' \
    -o "${prefix}_modbus.json" 2>/dev/null; then
    if jq -e '.value != null or .ok == true' "${prefix}_modbus.json" >/dev/null 2>&1; then
      modbus_ok=true
    else
      jq -e '.error' "${prefix}_modbus.json" >/dev/null 2>&1 && echo "[$ts] Modbus unavailable (continuing BACnet FDD)" | tee -a "$LOG_DIR/run.log"
    fi
  fi

  if curl "${CURL_TLS[@]}" -fsS -X POST "${BASE}/api/json-api/poll-once" \
    -H "Authorization: Bearer $INT_TOKEN" \
    -H 'Content-Type: application/json' \
    -d '{}' \
    -o "${prefix}_json_api.json" 2>/dev/null; then
    jq -e '.ok == true and (.http_status // 0) == 200' "${prefix}_json_api.json" >/dev/null 2>&1 && json_api_ok=true
  fi

  cycle_body='{}'
  if [[ -n "$phase" ]]; then
    cycle_body="$(jq -nc --arg p "$phase" '{simulation_phase:$p}')"
  fi

  if curl "${CURL_TLS[@]}" -fsS -X POST "${BASE}/api/bench/5007/smoke/cycle" \
    -H "Authorization: Bearer $AGENT_TOKEN" \
    -H 'Content-Type: application/json' \
    -d "$cycle_body" \
    -o "${prefix}_fdd_cycle.json" 2>/dev/null; then
    fdd_ok=true
    jq -e '.ok == true' "${prefix}_fdd_cycle.json" >/dev/null 2>&1 || fdd_ok=false
    data_source="$(jq -r '.fdd_eval.data_source // .capture.data_source // "unknown"' "${prefix}_fdd_cycle.json")"
    demo_only="$(jq -r '.proof.demo_only // true' "${prefix}_fdd_cycle.json")"
    raw_fault_count="$(jq -r '.proof.raw_fault_samples // 0' "${prefix}_fdd_cycle.json")"
    confirmed_fault_count="$(jq -r '.proof.confirmed_fault_count // 0' "${prefix}_fdd_cycle.json")"
    live_pass="$(jq -r '.proof.live_fdd_pass // false' "${prefix}_fdd_cycle.json")"
    if [[ "$live_pass" == "true" ]]; then LIVE_FDD_PASS=true; fi
    if [[ "$demo_only" == "false" ]]; then DEMO_ONLY=false; fi
    cp "${prefix}_fdd_cycle.json" "${prefix}_fdd.json"
  elif [[ "$SHORT_FDD" != "1" ]]; then
    # Long mode fallback: legacy SQL smoke against demo rule endpoint
    SQL="SELECT timestamp, equipment_id, oa_t, CASE WHEN oa_t IS NULL THEN false WHEN oa_t < 40.0 THEN true WHEN oa_t > 110.0 THEN true ELSE false END AS fault_raw FROM telemetry_pivot WHERE equipment_id = '5007'"
    if curl "${CURL_TLS[@]}" -fsS -X POST "${BASE}/api/fdd-rules/oa_temp_out_of_range/test-sql" \
      -H "Authorization: Bearer $INT_TOKEN" \
      -H 'Content-Type: application/json' \
      -d "$(jq -nc --arg sql "$SQL" '{sql:$sql,confirmation_seconds:300,use_historian:false}')" \
      -o "${prefix}_fdd.json" 2>/dev/null; then
      jq -e '.ok == true' "${prefix}_fdd.json" >/dev/null 2>&1 && fdd_ok=true
      data_source="demo:legacy-test-sql"
      demo_only=true
    fi
  fi

  if curl "${CURL_TLS[@]}" -fsS "${BASE}/api/historian/bench/5007/status" \
    -H "Authorization: Bearer $INT_TOKEN" \
    -o "${prefix}_historian.json" 2>/dev/null; then
    jq -e '.row_count >= 0' "${prefix}_historian.json" >/dev/null 2>&1 && historian_ok=true
  fi

  propose_ok=false
  if [[ "$SHORT_FDD" != "1" ]]; then
    if curl "${CURL_TLS[@]}" -fsS -X POST "${BASE}/api/fdd-wires/propose-assignments" \
      -H "Authorization: Bearer $AGENT_TOKEN" \
      -H 'Content-Type: application/json' \
      -d '{"site_id":"site:demo","equipment_type":"ahu","device_instance":5007}' \
      -o "${prefix}_propose.json" 2>/dev/null; then
      jq -e '.review_status == "needs_review"' "${prefix}_propose.json" >/dev/null 2>&1 && propose_ok=true
    fi
  fi

  jq -nc \
    --arg ts "$ts" \
    --arg mode "$MODE_LABEL" \
    --arg data_source "$data_source" \
    --arg phase "$phase" \
    --argjson n "$sample_n" \
    --argjson health "$health_ok" \
    --argjson tree "$tree_ok" \
    --argjson modbus "$modbus_ok" \
    --argjson json_api "$json_api_ok" \
    --argjson historian "$historian_ok" \
    --argjson fdd "$fdd_ok" \
    --argjson propose "$propose_ok" \
    --argjson demo_only "$demo_only" \
    --argjson live_pass "$live_pass" \
    --argjson raw_fault "$raw_fault_count" \
    --argjson confirmed_fault "$confirmed_fault_count" \
    '{timestamp:$ts,sample:$n,mode:$mode,data_source:$data_source,simulation_phase:$phase,health:$health,tree:$tree,modbus:$modbus,json_api:$json_api,historian:$historian,fdd:$fdd,propose:$propose,demo_only:$demo_only,live_fdd_pass:$live_pass,raw_fault_samples:$raw_fault,confirmed_fault_count:$confirmed_fault}' \
    >>"$LOG_DIR/summary.jsonl"

  echo "[$ts] sample=$sample_n phase=$phase health=$health_ok tree=$tree_ok modbus=$modbus_ok json_api=$json_api_ok historian=$historian_ok fdd=$fdd_ok source=$data_source demo_only=$demo_only live_pass=$live_pass raw=$raw_fault_count confirmed=$confirmed_fault_count"

  remaining=$(( END - $(date +%s) ))
  if [[ -n "$SAMPLES" && $sample_n -ge $SAMPLES ]]; then
    break
  fi
  if [[ "$SHORT_FDD" == "1" && $remaining -le 0 ]]; then
    break
  fi
  if [[ "$SHORT_FDD" != "1" && -z "$SAMPLES" && $remaining -le 0 ]]; then
    break
  fi
  sleep_for=$INTERVAL
  if [[ "$SHORT_FDD" != "1" && -z "$SAMPLES" && $remaining -lt $sleep_for ]]; then
    sleep_for=$remaining
  fi
  if [[ $sample_n -lt ${SAMPLES:-999999} ]]; then
    sleep "$sleep_for"
  else
    break
  fi
done

echo "Finished: $(date -Iseconds)" | tee -a "$LOG_DIR/run.log"

# Final eval artifact
curl "${CURL_TLS[@]}" -fsS "${BASE}/api/bench/5007/smoke/status" \
  -H "Authorization: Bearer $INT_TOKEN" \
  -o "$LOG_DIR/final_status.json" 2>/dev/null || true

fail_count="$(jq -s '[.[] | select(.health==false or .tree==false or .fdd==false)] | length' "$LOG_DIR/summary.jsonl" 2>/dev/null || echo 0)"
total="$(wc -l <"$LOG_DIR/summary.jsonl" | tr -d ' ')"
echo "Samples: $total interval_failures: $fail_count" | tee -a "$LOG_DIR/run.log"

if [[ "$SHORT_FDD" == "1" ]]; then
  if [[ "$DEMO_ONLY" == "true" && "$SIMULATE" != "1" ]]; then
    echo "FAIL: short FDD ended DEMO ONLY — not a live FDD pass" | tee -a "$LOG_DIR/run.log" >&2
    exit 1
  fi
  if [[ "$LIVE_FDD_PASS" != "true" ]]; then
    echo "FAIL: short FDD did not prove raw+confirmed fault transitions" | tee -a "$LOG_DIR/run.log" >&2
    echo "Inspect $LOG_DIR/final_status.json and summary.jsonl" >&2
    exit 1
  fi
  echo "PASS: short FDD proof complete (data_source=$(jq -r '.data_source' "$LOG_DIR/final_status.json" 2>/dev/null))" | tee -a "$LOG_DIR/run.log"
  exit 0
fi

if [[ "$fail_count" -gt 0 ]]; then
  echo "WARN: some intervals failed — inspect $LOG_DIR/summary.jsonl" >&2
  exit 1
fi
echo "Bench 5007 long smoke passed." | tee -a "$LOG_DIR/run.log"
