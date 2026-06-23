#!/usr/bin/env bash
# Long-running bench device 5007 smoke: capture driver tree, FDD SQL, assignments.
#
#   BENCH_SMOKE_HOURS=6 ./scripts/bench_5007_long_smoke.sh
#   BENCH_SMOKE_INTERVAL_SEC=300  # default 5 min between samples
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
HOURS="${BENCH_SMOKE_HOURS:-6}"
INTERVAL="${BENCH_SMOKE_INTERVAL_SEC:-300}"
SAMPLES="${BENCH_SMOKE_SAMPLES:-}"
LOG_DIR="${BENCH_SMOKE_LOG_DIR:-$ROOT/workspace/logs/bench_5007_long_smoke}"
AUTH="$ROOT/workspace/auth.env.local"
if [[ -n "$SAMPLES" ]]; then
  END=0
else
  END=$(( $(date +%s) + HOURS * 3600 ))
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

echo "Bench 5007 long smoke: ${HOURS}h interval=${INTERVAL}s log=$LOG_DIR"
echo "Started: $(date -Iseconds)" | tee -a "$LOG_DIR/run.log"

sample_n=0
while true; do
  sample_n=$((sample_n + 1))
  ts="$(date -Iseconds)"
  prefix="${LOG_DIR}/capture_${ts//:/-}"

  health_ok=false
  tree_ok=false
  fdd_ok=false
  propose_ok=false

  if curl "${CURL_TLS[@]}" -fsS "${BASE}/api/health" >/dev/null 2>&1; then
    health_ok=true
  fi

  if curl "${CURL_TLS[@]}" -fsS "${BASE}/api/bacnet/driver/tree" \
    -H "Authorization: Bearer $INT_TOKEN" \
    -o "${prefix}_tree.json" 2>/dev/null; then
    tree_ok=true
    jq -e '.drivers | length >= 1' "${prefix}_tree.json" >/dev/null 2>&1 || tree_ok=false
  fi

  SQL='SELECT timestamp, equipment_id, oa_t, CASE WHEN oa_t IS NULL THEN false WHEN oa_t < 40.0 THEN true WHEN oa_t > 110.0 THEN true ELSE false END AS fault_raw FROM telemetry_pivot WHERE equipment_id = '\''AHU-1'\'''
  if curl "${CURL_TLS[@]}" -fsS -X POST "${BASE}/api/fdd-rules/oa_temp_out_of_range/test-sql" \
    -H "Authorization: Bearer $INT_TOKEN" \
    -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg sql "$SQL" '{sql:$sql,confirmation_seconds:300}')" \
    -o "${prefix}_fdd.json" 2>/dev/null; then
    jq -e '.ok == true' "${prefix}_fdd.json" >/dev/null 2>&1 && fdd_ok=true
  fi

  if curl "${CURL_TLS[@]}" -fsS -X POST "${BASE}/api/fdd-wires/propose-assignments" \
    -H "Authorization: Bearer $AGENT_TOKEN" \
    -H 'Content-Type: application/json' \
    -d '{"site_id":"site:demo","equipment_type":"ahu"}' \
    -o "${prefix}_propose.json" 2>/dev/null; then
    jq -e '.review_status == "needs_review"' "${prefix}_propose.json" >/dev/null 2>&1 && propose_ok=true
  fi

  jq -nc \
    --arg ts "$ts" \
    --argjson n "$sample_n" \
    --argjson health "$health_ok" \
    --argjson tree "$tree_ok" \
    --argjson fdd "$fdd_ok" \
    --argjson propose "$propose_ok" \
    '{timestamp:$ts,sample:$n,health:$health,tree:$tree,fdd_test:$fdd,propose:$propose}' \
    >>"$LOG_DIR/summary.jsonl"

  echo "[$ts] sample=$sample_n health=$health_ok tree=$tree_ok fdd=$fdd_ok propose=$propose_ok"

  remaining=$(( END - $(date +%s) ))
  if [[ -n "$SAMPLES" && $sample_n -ge $SAMPLES ]]; then
    break
  fi
  if [[ -z "$SAMPLES" && $remaining -le 0 ]]; then
    break
  fi
  if [[ -z "$SAMPLES" ]]; then
    sleep_for=$INTERVAL
    if [[ $remaining -lt $sleep_for ]]; then
      sleep_for=$remaining
    fi
    sleep "$sleep_for"
  elif [[ $sample_n -lt $SAMPLES ]]; then
    sleep "$INTERVAL"
  else
    break
  fi
done

echo "Finished: $(date -Iseconds)" | tee -a "$LOG_DIR/run.log"
fail_count="$(jq -s '[.[] | select(.health==false or .tree==false or .fdd_test==false)] | length' "$LOG_DIR/summary.jsonl" 2>/dev/null || echo 0)"
total="$(wc -l <"$LOG_DIR/summary.jsonl" | tr -d ' ')"
echo "Samples: $total failures: $fail_count"
if [[ "$fail_count" -gt 0 ]]; then
  echo "WARN: some intervals failed — inspect $LOG_DIR/summary.jsonl" >&2
  exit 1
fi
echo "Bench 5007 long smoke passed."
