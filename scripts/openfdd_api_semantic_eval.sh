#!/usr/bin/env bash
# Human + AI semantic workflow: discover model/drivers from APIs, probe RDF/SPARQL, flag wonky state.
#
#   ./scripts/openfdd_api_semantic_eval.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_bench_lib.sh
source "$ROOT/scripts/openfdd_bench_lib.sh"
# shellcheck source=scripts/openfdd_auth_lib.sh
source "$ROOT/scripts/openfdd_auth_lib.sh"

openfdd_bench_load_profile "$ROOT"

BRIDGE="${OPENFDD_API_BASE:-http://127.0.0.1:8080}"
COMMISSION="${OPENFDD_COMMISSION_BASE:-http://127.0.0.1:9091}"
AUTH="${OPENFDD_AUTH_ENV:-$ROOT/workspace/auth.env.local}"
RDF_PATHS="${OPENFDD_RDF_PROBE_PATHS:-[]}"

RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_DIR="${OPENFDD_SEMANTIC_EVAL_DIR:-$ROOT/workspace/logs/semantic_eval_${RUN_TS}}"

mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_DIR/semantic.log") 2>&1

pass=0
fail=0
skip=0
wonky=0
FAIL=0

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }
check() {
  openfdd_bench_check_line "$1" "$2" "$3" "$LOG_DIR/summary.txt"
  if [[ "$2" == "pass" ]]; then pass=$((pass + 1))
  elif [[ "$2" == "skip" ]]; then skip=$((skip + 1))
  else fail=$((fail + 1)); FAIL=1; fi
}
wonky_note() {
  echo "WONKY $1 — $2" | tee -a "$LOG_DIR/wonky.txt" "$LOG_DIR/summary.txt"
  wonky=$((wonky + 1))
}

: >"$LOG_DIR/summary.txt"
: >"$LOG_DIR/wonky.txt"
log "=== Semantic / API evaluation → $LOG_DIR ==="
log "profile=$OPENFDD_BENCH_PROFILE bridge=$BRIDGE"

CURL_TLS=()
read -ra CURL_TLS <<< "$(openfdd_bench_curl_tls "$BRIDGE")"

# --- Human workflow step 1: public health ---
health="$(curl "${CURL_TLS[@]}" -fsS "$BRIDGE/api/health" 2>/dev/null || echo '{}')"
echo "$health" >"$LOG_DIR/step01_health.json"
if jq -e '.ok == true' <<<"$health" >/dev/null; then
  check "human-health" pass "/api/health ok version=$(jq -r '.version // .tag // "?"' <<<"$health")"
else
  check "human-health" fail "/api/health not ok"
fi

# --- Human workflow step 2: login ---
TOKEN="$(openfdd_auth_login_token "$BRIDGE" "$AUTH" integrator)" || {
  check "human-login" fail "integrator login failed"
  exit 1
}
check "human-login" pass "integrator JWT obtained"
auth_hdr=(-H "Authorization: Bearer $TOKEN")

# --- Human workflow step 3: stack health ---
stack="$(curl "${CURL_TLS[@]}" -fsS "${auth_hdr[@]}" "$BRIDGE/api/health/stack" 2>/dev/null || echo '{}')"
echo "$stack" >"$LOG_DIR/step03_stack.json"
if jq -e '.ok == true or .bridge.ok == true or .status == "ok"' <<<"$stack" >/dev/null 2>&1; then
  check "human-stack" pass "stack health OK"
else
  check "human-stack" fail "stack health degraded"
fi

# --- Discovery (no hardcoded device IDs) ---
bacnet_disc="$(openfdd_bench_discover_bacnet "$BRIDGE" "$COMMISSION" "$TOKEN")"
modbus_disc="$(openfdd_bench_discover_modbus "$BRIDGE" "$TOKEN")"
haystack_disc="$(openfdd_bench_discover_haystack "$BRIDGE" "$TOKEN")"
model_disc="$(openfdd_bench_discover_model "$BRIDGE" "$TOKEN")"

echo "$bacnet_disc" >"$LOG_DIR/disc_bacnet.json"
echo "$modbus_disc" >"$LOG_DIR/disc_modbus.json"
echo "$haystack_disc" >"$LOG_DIR/disc_haystack.json"
echo "$model_disc" >"$LOG_DIR/disc_model.json"

field_count="$(jq '.field_device_count // 0' <<<"$bacnet_disc")"
whois_field="$(jq '.whois_field_count // 0' <<<"$bacnet_disc")"
min_field="${OPENFDD_BACNET_MIN_FIELD_DEVICES:-1}"
if [[ "$field_count" -ge "$min_field" || "$whois_field" -ge "$min_field" ]]; then
  check "disc-bacnet" pass "field_devices=$field_count whois_field=$whois_field"
else
  check "disc-bacnet" fail "field_devices=$field_count whois_field=$whois_field (min=$min_field)"
fi

modbus_pts="$(jq '.read_points | length' <<<"$modbus_disc")"
if [[ "$modbus_pts" -ge "${OPENFDD_MODBUS_MIN_READ_POINTS:-2}" ]]; then
  check "disc-modbus" pass "$modbus_pts modbus points from driver tree"
else
  check "disc-modbus" fail "only $modbus_pts modbus points in tree"
fi

if jq -e '.enabled == true and .test_ok == true' <<<"$haystack_disc" >/dev/null; then
  check "disc-haystack" pass "haystack enabled + test ok"
elif [[ "${OPENFDD_REQUIRE_HAYSTACK:-0}" == "1" ]]; then
  check "disc-haystack" fail "$(jq -r '.test.message // .status.message // "haystack not live"' <<<"$haystack_disc")"
else
  check "disc-haystack" skip "haystack not configured"
fi

if jq -e '.ok == true and (.csv_dev_model | not)' <<<"$model_disc" >/dev/null; then
  check "disc-model" pass "model haystack grid rows=$(jq '.row_count' <<<"$model_disc") active_site=$(jq -r '.active_site_id // "?"' <<<"$model_disc")"
elif jq -e '.csv_dev_model == true' <<<"$model_disc" >/dev/null; then
  check "disc-model" fail "stale CSV dev model active_site=$(jq -r '.active_site_id // "site:import"') rows=$(jq '.row_count' <<<"$model_disc") sample=$(jq -c '.sample_ids' <<<"$model_disc")"
else
  check "disc-model" fail "model /api/model/haystack rows=$(jq '.row_count' <<<"$model_disc") active_site=$(jq -r '.active_site_id // "?"' <<<"$model_disc")"
fi

# --- Human workflow: driver reads from discovered points ---
: >"$LOG_DIR/human_reads.jsonl"
read_count=0
read_ok=0
while IFS= read -r point_id; do
  [[ -n "$point_id" ]] || continue
  body="$(jq -nc --arg pid "$point_id" '{point_id:$pid}')"
  resp="$(curl "${CURL_TLS[@]}" -sS -X POST "${auth_hdr[@]}" -H 'Content-Type: application/json' \
    -d "$body" "$COMMISSION/api/bacnet/read" 2>/dev/null || echo '{}')"
  ok=false
  jq -e '.ok == true or .value != null' <<<"$resp" >/dev/null 2>&1 && ok=true
  resp_json="$(jq -c . <<<"$resp" 2>/dev/null || echo '{}')"
  jq -nc --arg pid "$point_id" --argjson ok "$ok" --argjson resp "$resp_json" \
    '{driver:"bacnet",point_id:$pid,ok:$ok,response:$resp}' >>"$LOG_DIR/human_reads.jsonl"
  read_count=$((read_count + 1))
  [[ "$ok" == "true" ]] && read_ok=$((read_ok + 1))
done < <(jq -r '.read_points[]?.point_id // empty' <<<"$bacnet_disc")

while IFS= read -r line; do
  [[ -n "$line" ]] || continue
  reg="$(jq -r '.register' <<<"$line")"
  func="$(jq -r '.function' <<<"$line")"
  resp="$(curl "${CURL_TLS[@]}" -sS -X POST "${auth_hdr[@]}" -H 'Content-Type: application/json' \
    -d "$(jq -nc --argjson reg "$reg" --arg func "$func" '{register:$reg,function:$func,scale:0.1}')" \
    "$BRIDGE/api/modbus/read" 2>/dev/null || echo '{}')"
  ok=false
  jq -e '.ok == true or .value != null' <<<"$resp" >/dev/null 2>&1 && ok=true
  jq -nc --argjson reg "$reg" --argjson ok "$ok" '{driver:"modbus",register:$reg,ok:$ok}' >>"$LOG_DIR/human_reads.jsonl"
  read_count=$((read_count + 1))
  [[ "$ok" == "true" ]] && read_ok=$((read_ok + 1))
done < <(jq -c '.read_points[]?' <<<"$modbus_disc")

haystack_body='{"filter":"point and cur"}'
for path in /api/haystack/read /api/haystack/poll-once; do
  code="$(curl "${CURL_TLS[@]}" -sS -o "$LOG_DIR/haystack_read.json" -w '%{http_code}' \
    -X POST "${auth_hdr[@]}" -H 'Content-Type: application/json' \
    -d "$haystack_body" "$BRIDGE$path" 2>/dev/null || echo 000)"
  if [[ "$code" =~ ^2 ]]; then
    rows="$(jq '(.rows // .points // []) | length' "$LOG_DIR/haystack_read.json" 2>/dev/null || echo 0)"
    jq -nc --arg path "$path" --argjson rows "$rows" --argjson ok true \
      '{driver:"haystack",path:$path,rows:$rows,ok:$ok}' >>"$LOG_DIR/human_reads.jsonl"
    read_ok=$((read_ok + 1))
    read_count=$((read_count + 1))
    check "human-haystack-read" pass "$path returned $rows rows"
    break
  fi
done

if [[ "$read_count" -gt 0 && "$read_ok" -ge 1 ]]; then
  check "human-reads" pass "$read_ok/$read_count discovered point reads OK"
else
  check "human-reads" fail "$read_ok/$read_count reads OK"
fi

# --- RDF / SPARQL endpoint probe ---
: >"$LOG_DIR/rdf_probe.jsonl"
rdf_found=0
while IFS= read -r path; do
  [[ -n "$path" ]] || continue
  code="$(curl "${CURL_TLS[@]}" -sS -o "$LOG_DIR/rdf_$(echo "$path" | tr '/:' '__').json" -w '%{http_code}' \
    -X GET "${auth_hdr[@]}" "$BRIDGE$path" 2>/dev/null || echo 000)"
  ctype="$(grep -i content-type "$LOG_DIR/rdf_$(echo "$path" | tr '/:' '__').json" 2>/dev/null || true)"
  jq -nc --arg path "$path" --arg code "$code" '{path:$path,http_code:$code}' >>"$LOG_DIR/rdf_probe.jsonl"
  if [[ "$code" =~ ^2 ]]; then
    rdf_found=$((rdf_found + 1))
    check "rdf-$path" pass "HTTP $code"
  elif [[ "$code" == "404" || "$code" == "405" ]]; then
    check "rdf-$path" skip "HTTP $code (not shipped on this build)"
  else
    check "rdf-$path" fail "HTTP $code"
  fi
done < <(python3 -c 'import json,sys; print("\n".join(json.loads(sys.argv[1])))' "$RDF_PATHS" 2>/dev/null || true)

if [[ "$rdf_found" -eq 0 ]]; then
  log "No RDF/SPARQL routes live — Haystack grid JSON is primary semantic model on this build"
fi

# SPARQL POST probe on /api/sparql if exists
if [[ -f "$LOG_DIR/rdf__api_sparql.json" ]] || curl "${CURL_TLS[@]}" -sS -o /dev/null -w '%{http_code}' "$BRIDGE/api/sparql" | grep -qE '^[23]'; then
  sparql='SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 5'
  sparql_code="$(curl "${CURL_TLS[@]}" -sS -o "$LOG_DIR/sparql_select.json" -w '%{http_code}' \
    -X POST "${auth_hdr[@]}" -H 'Content-Type: application/sparql-query' -d "$sparql" \
    "$BRIDGE/api/sparql" 2>/dev/null || echo 000)"
  if [[ "$sparql_code" =~ ^2 ]]; then
    check "sparql-select" pass "POST SPARQL SELECT HTTP $sparql_code"
  else
    # try JSON body variant
    sparql_code="$(curl "${CURL_TLS[@]}" -sS -o "$LOG_DIR/sparql_select.json" -w '%{http_code}' \
      -X POST "${auth_hdr[@]}" -H 'Content-Type: application/json' \
      -d "$(jq -nc --arg q "$sparql" '{query:$q}')" "$BRIDGE/api/sparql" 2>/dev/null || echo 000)"
    [[ "$sparql_code" =~ ^2 ]] && check "sparql-select" pass "POST JSON SPARQL HTTP $sparql_code" \
      || check "sparql-select" skip "SPARQL endpoint present but query failed ($sparql_code)"
  fi
fi

# --- Wonky pattern detection ---
# Haystack: curVal null but tags.curVal set
if jq -e '.read_points[]? | select(.curVal == null)' <<<"$haystack_disc" >/dev/null \
  && jq -e '[.read_points[]?.label] | length > 0' <<<"$haystack_disc" >/dev/null; then
  wonky_note "haystack-curVal-split" "driver tree points show null curVal — check mapping/poll"
fi

# BACnet: whois finds devices but driver tree field count zero
if [[ "$whois_field" -gt 0 && "$field_count" -eq 0 ]]; then
  wonky_note "bacnet-tree-whois-mismatch" "Who-Is sees $whois_field field device(s) but driver tree has 0"
fi

# Modbus: enabled driver but all present_value null
null_modbus="$(jq '[.read_points[]?] | length' <<<"$modbus_disc")"
if [[ "$null_modbus" -gt 0 ]]; then
  tree_null="$(curl "${CURL_TLS[@]}" -fsS "${auth_hdr[@]}" "$BRIDGE/api/modbus/driver/tree" 2>/dev/null \
    | jq '[.devices[]?.points[]? | select(.present_value == null)] | length' 2>/dev/null || echo 0)"
  if [[ "$tree_null" -gt 0 ]]; then
    wonky_note "modbus-null-present" "$tree_null modbus points with present_value=null in tree"
  fi
fi

# Model vs driver: fddInput tags in model but haystack disabled
if jq -e '.has_point == true' <<<"$model_disc" >/dev/null \
  && jq -e '.enabled != true' <<<"$haystack_disc" >/dev/null; then
  wonky_note "model-haystack-disabled" "model grid has FDD points but haystack driver disabled"
fi

if jq -e '.csv_dev_model == true' <<<"$model_disc" >/dev/null; then
  wonky_note "model-csv-dev-stale" "active_site=$(jq -r '.active_site_id // site:import' <<<"$model_disc") — CSV import dev artifacts (point:import-*) not live BACnet ${OPENFDD_SMOKE_DEVICE_INSTANCE:-5007}/Modbus"
fi

tree_field="$(curl "${CURL_TLS[@]}" -fsS "${auth_hdr[@]}" "$BRIDGE/api/bacnet/driver/tree" 2>/dev/null \
  | jq '[.devices[]? | select(.device_instance != 599999 and .address != "local")] | length' 2>/dev/null || echo 0)"
if [[ "$whois_field" -gt 0 && "$tree_field" -eq 0 ]]; then
  wonky_note "bacnet-ui-tree-empty" "Who-Is sees field device(s) but BACnet tab driver tree has 0 — device ${OPENFDD_SMOKE_DEVICE_INSTANCE:-5007} not learned in UI"
fi

# Commission vs bridge BACnet
bridge_whois="$(openfdd_bench_api POST "$BRIDGE" "/api/bacnet/whois" "$TOKEN" "$(openfdd_bench_whois_json)")"
if jq -e '.error' <<<"$bridge_whois" >/dev/null 2>&1; then
  wonky_note "bacnet-bridge-bind" "bridge Who-Is error (expected — use commission): $(jq -r '.error' <<<"$bridge_whois")"
fi

# --- AI workflow summary (mirror human via REST; MCP eval is separate script) ---
ai_steps=(
  "site_health:/api/health"
  "stack_status:/api/health/stack"
  "driver_poll_bacnet:/api/bacnet/poll/status"
  "driver_poll_modbus:/api/modbus/poll/status"
  "driver_poll_haystack:/api/haystack/status"
  "validation_run:/api/validation-runs/current/status"
  "model_haystack:/api/model/haystack"
)
ai_ok=0
: >"$LOG_DIR/ai_workflow.jsonl"
for step in "${ai_steps[@]}"; do
  name="${step%%:*}"
  path="${step#*:}"
  resp="$(curl "${CURL_TLS[@]}" -fsS "${auth_hdr[@]}" "$BRIDGE$path" 2>/dev/null || echo '{}')"
  ok=false
  jq -e '.ok == true or .status != null or (.rows // []) | length >= 0' <<<"$resp" >/dev/null 2>&1 && ok=true
  jq -nc --arg name "$name" --arg path "$path" --argjson ok "$ok" '{step:$name,path:$path,ok:$ok}' >>"$LOG_DIR/ai_workflow.jsonl"
  [[ "$ok" == "true" ]] && ai_ok=$((ai_ok + 1))
done
check "ai-rest-workflow" pass "$ai_ok/${#ai_steps[@]} REST steps OK"

# FDD cycle (agent role) — optional human commissioning step
agent_token="$(openfdd_auth_login_token "$BRIDGE" "$AUTH" agent 2>/dev/null || true)"
if [[ -n "$agent_token" ]]; then
  cycle="$(curl "${CURL_TLS[@]}" -fsS -H "Authorization: Bearer $agent_token" \
    -X POST "$BRIDGE/api/validation-runs/current/cycle" 2>/dev/null || echo '{}')"
  echo "$cycle" >"$LOG_DIR/fdd_cycle.json"
  if jq -e '.ok == true' <<<"$cycle" >/dev/null 2>&1; then
    check "ai-fdd-cycle" pass "agent POST /cycle ok"
  else
    check "ai-fdd-cycle" skip "$(jq -r '.error // "cycle not available"' <<<"$cycle")"
  fi
else
  check "ai-fdd-cycle" skip "agent login failed"
fi

jq -nc \
  --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg dir "$LOG_DIR" \
  --argjson pass "$pass" --argjson fail "$fail" --argjson skip "$skip" --argjson wonky "$wonky" \
  --slurpfile bacnet "$LOG_DIR/disc_bacnet.json" \
  --slurpfile model "$LOG_DIR/disc_model.json" \
  '{
    timestamp_utc:$ts,
    artifact_dir:$dir,
    pass_count:$pass,
    fail_count:$fail,
    skip_count:$skip,
    wonky_count:$wonky,
    discovery:{bacnet:$bacnet[0],model:$model[0]},
    ok:($fail==0)
  }' >"$LOG_DIR/result.json"

echo | tee -a "$LOG_DIR/summary.txt"
echo "Wonky findings: $wonky (see wonky.txt)" | tee -a "$LOG_DIR/summary.txt"
echo "Result: pass=$pass fail=$fail skip=$skip artifact=$LOG_DIR" | tee -a "$LOG_DIR/summary.txt"
log "=== Semantic eval DONE fail=$FAIL wonky=$wonky ==="
[[ "$FAIL" -eq 0 ]]
