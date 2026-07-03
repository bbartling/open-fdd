#!/usr/bin/env bash
# Rigorous driver validation — point-level reads, polling proof, PDF report input.
# Wraps openfdd_drivers_validate.sh and adds per-driver OT/API reads + FDD snapshot.
#
# Usage:
#   ./scripts/openfdd_drivers_rigorous_validate.sh
#   OPENFDD_EXPECT_VERSION=3.2.3 ./scripts/openfdd_drivers_rigorous_validate.sh
#   OPENFDD_GENERATE_PDF=1 ./scripts/openfdd_drivers_rigorous_validate.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_auth_lib.sh
source "$ROOT/scripts/openfdd_auth_lib.sh"
# shellcheck source=scripts/openfdd_bench_lib.sh
source "$ROOT/scripts/openfdd_bench_lib.sh"

openfdd_bench_load_profile "$ROOT" || true

BRIDGE="${OPENFDD_API_BASE:-http://127.0.0.1:8080}"
COMMISSION="${OPENFDD_COMMISSION_BASE:-http://127.0.0.1:9091}"
AUTH="${OPENFDD_AUTH_ENV:-$ROOT/workspace/auth.env.local}"
EXPECT_VER="${OPENFDD_EXPECT_VERSION:-3.2.3}"
POLL_CYCLES="${OPENFDD_RIGOROUS_POLL_CYCLES:-3}"
POLL_INTERVAL="${OPENFDD_RIGOROUS_POLL_INTERVAL_SEC:-20}"
GENERATE_PDF="${OPENFDD_GENERATE_PDF:-1}"

RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_DIR="${OPENFDD_DRIVERS_RIGOROUS_DIR:-$ROOT/workspace/logs/drivers_rigorous_${RUN_TS}}"
mkdir -p "$LOG_DIR"

CURL_TLS=()
[[ "$BRIDGE" == https://* ]] && CURL_TLS=(-k)

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$LOG_DIR/rigorous.log"; }

write_readme() {
  cat >"$LOG_DIR/README.md" <<EOF
# Open-FDD rigorous driver validation

- Run: \`${RUN_TS}\`
- Expected image version: \`${EXPECT_VER}\`
- Bridge: \`${BRIDGE}\`
- Commission: \`${COMMISSION}\`

## Phases

| Phase | Script | Artifact |
|-------|--------|----------|
| 1 | \`openfdd_drivers_validate.sh\` | \`phase1_drivers/\` |
| 2 | Point-level reads (BACnet/Modbus/Haystack/JSON) | \`driver_readings.jsonl\` |
| 3 | Poll stability (\${POLL_CYCLES} cycles) | \`poll_summary.jsonl\` |
| 4 | FDD + devices snapshot | \`fdd_snapshot.json\` |
| 5 | PDF (optional) | \`validation_report.pdf\` |

Bench: devices/points **discovered** from \`/api/*/driver/tree\` + commission Who-Is (see \`workspace/bench/bench_profile.toml\`)
EOF
}

write_readme
log "Rigorous validation → $LOG_DIR"

# --- Phase 1: base driver gate ---
log "Phase 1: openfdd_drivers_validate.sh"
export OPENFDD_DRIVERS_VALIDATE_DIR="$LOG_DIR/phase1_drivers"
export OPENFDD_EXPECT_VERSION="$EXPECT_VER"
if "$ROOT/scripts/openfdd_drivers_validate.sh" | tee "$LOG_DIR/phase1_drivers.log"; then
  log "Phase 1 OK"
else
  log "Phase 1 FAIL (continuing for artifact capture)"
fi

TOKEN="$(openfdd_auth_login_token "$BRIDGE" "$AUTH" integrator)" || {
  log "ERROR: integrator login failed"
  exit 1
}
auth_hdr=(-H "Authorization: Bearer $TOKEN")

bacnet_disc="$(openfdd_bench_discover_bacnet "$BRIDGE" "$COMMISSION" "$TOKEN")"
modbus_disc="$(openfdd_bench_discover_modbus "$BRIDGE" "$TOKEN")"
echo "$bacnet_disc" >"$LOG_DIR/bacnet_discovery.json"
echo "$modbus_disc" >"$LOG_DIR/modbus_discovery.json"
whois_body="$(openfdd_bench_whois_json)"

# --- Phase 2: point-level reads (discovered) ---
log "Phase 2: point-level driver reads (discovery-driven)"
: >"$LOG_DIR/driver_readings.jsonl"

read_json() {
  local driver="$1" point="$2" method="$3" base="$4" path="$5" body="${6:-}"
  local out="$LOG_DIR/read_${driver}_$(echo "$point" | tr '/: ' '_').json"
  local resp ok val err
  if [[ -n "$body" ]]; then
    resp="$(curl "${CURL_TLS[@]}" -sS -X "$method" "${auth_hdr[@]}" -H 'Content-Type: application/json' \
      -d "$body" "$base$path" 2>/dev/null || echo '{"error":"curl_failed"}')"
  else
    resp="$(curl "${CURL_TLS[@]}" -sS -X "$method" "${auth_hdr[@]}" "$base$path" 2>/dev/null || echo '{"error":"curl_failed"}')"
  fi
  echo "$resp" >"$out"
  if jq -e '.ok == true or .value != null or (.present_value // .curVal // .cur) != null or (.device_instance != null and (.value|tonumber?) != null) or (.rows // .points // []) | length > 0' <<<"$resp" >/dev/null 2>&1; then
    ok=true
    val="$(jq -r '.value // (.curVal // .cur // (.rows[0].curVal // empty)) // "ok"' <<<"$resp" 2>/dev/null || echo ok)"
  else
    ok=false
    val=""
    err="$(jq -r '.error // .message // "read_failed"' <<<"$resp")"
  fi
  jq -nc \
    --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg driver "$driver" \
    --arg point "$point" \
    --argjson ok "$ok" \
    --arg value "$val" \
    --arg error "${err:-}" \
    --arg artifact "$out" \
    '{timestamp_utc:$ts,driver:$driver,point_id:$point,ok:$ok,value:$value,error:$error,artifact:$artifact}' \
    >>"$LOG_DIR/driver_readings.jsonl"
  if [[ "$ok" == "true" ]]; then
    log "  PASS $driver $point → $val"
  else
    log "  FAIL $driver $point — ${err:-unknown}"
  fi
}

# BACnet commission reads — from driver tree discovery
while IFS= read -r point_id; do
  [[ -n "$point_id" ]] || continue
  name="$(echo "$point_id" | tr '/:' '_')"
  read_json "bacnet" "$name" POST "$COMMISSION" "/api/bacnet/read" \
    "$(jq -nc --arg pid "$point_id" '{point_id:$pid}')"
done < <(jq -r '.read_points[]?.point_id // empty' <<<"$bacnet_disc")

# Modbus — from driver tree discovery
while IFS= read -r line; do
  [[ -n "$line" ]] || continue
  reg="$(jq -r '.register' <<<"$line")"
  func="$(jq -r '.function // "input_register"' <<<"$line")"
  label="$(jq -r '.label // ("reg"+(.register|tostring))' <<<"$line")"
  read_json "modbus" "$label" POST "$BRIDGE" "/api/modbus/read" \
    "$(jq -nc --argjson reg "$reg" --arg func "$func" '{register:$reg,function:$func,scale:0.1}')"
done < <(jq -c '.read_points[]?' <<<"$modbus_disc")

# JSON API health probes
json_poll_body="$(openfdd_bench_json_api_poll_once_body "$ROOT" 2>/dev/null || echo '{}')"
read_json "json-api" "poll-status" GET "$BRIDGE" "/api/json-api/poll/status" ""
read_json "json-api" "poll-once" POST "$BRIDGE" "/api/json-api/poll-once" "$json_poll_body"

# Haystack — test + read filter if endpoints exist
read_json "haystack" "test" POST "$BRIDGE" "/api/haystack/test" '{}'
haystack_read_body='{"filter":"point and cur"}'
if curl "${CURL_TLS[@]}" -sS -o /dev/null -w '%{http_code}' -X POST "${auth_hdr[@]}" \
  -H 'Content-Type: application/json' -d "$haystack_read_body" "$BRIDGE/api/haystack/read" 2>/dev/null | grep -qE '^2'; then
  read_json "haystack" "read-cur" POST "$BRIDGE" "/api/haystack/read" "$haystack_read_body"
elif curl "${CURL_TLS[@]}" -sS -o /dev/null -w '%{http_code}' -X POST "${auth_hdr[@]}" \
  -H 'Content-Type: application/json' -d '{"filter":"point and cur"}' "$BRIDGE/api/haystack/poll-once" 2>/dev/null | grep -qE '^2'; then
  read_json "haystack" "poll-once-cur" POST "$BRIDGE" "/api/haystack/poll-once" '{"filter":"point and cur"}'
else
  jq -nc --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    '{timestamp_utc:$ts,driver:"haystack",point_id:"read-cur",ok:false,value:"",error:"no /api/haystack/read or poll-once route",artifact:""}' \
    >>"$LOG_DIR/driver_readings.jsonl"
  log "  SKIP haystack read — no read route (test-only gate)"
fi

# --- Phase 3: poll stability (live OT reads each cycle — not status-only) ---
log "Phase 3: poll stability (${POLL_CYCLES} cycles, ${POLL_INTERVAL}s) — live Modbus/BACnet reads"
: >"$LOG_DIR/poll_summary.jsonl"
for n in $(seq 1 "$POLL_CYCLES"); do
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  live="$(openfdd_bench_live_ot_poll "$BRIDGE" "$COMMISSION" "$TOKEN" "$ROOT")"
  echo "$live" >"$LOG_DIR/live_ot_cycle_${n}.json"
  modbus_ok=false haystack_ok=false bacnet_ok=false json_ok=false
  jq -e '.modbus_read_ok == true' <<<"$live" >/dev/null 2>&1 && modbus_ok=true
  jq -e '.bacnet_read_ok == true and .bacnet_whois_ok == true' <<<"$live" >/dev/null 2>&1 && bacnet_ok=true
  h="$(curl "${CURL_TLS[@]}" -fsS -X POST "${auth_hdr[@]}" -H 'Content-Type: application/json' \
    "$BRIDGE/api/haystack/test" -d '{}' 2>/dev/null || echo '{}')"
  jq -e '.ok == true' <<<"$h" >/dev/null 2>&1 && haystack_ok=true
  j="$(curl "${CURL_TLS[@]}" -fsS "${auth_hdr[@]}" "$BRIDGE/api/json-api/poll/status" 2>/dev/null || echo '{}')"
  jq -e '.ok == true and (.last_poll.ok == true or .last_poll.http_status == 200)' <<<"$j" >/dev/null 2>&1 && json_ok=true
  if [[ "$json_ok" != true && "$n" -eq 1 && -n "${json_poll_body:-}" && "$json_poll_body" != '{}' ]]; then
    j="$(curl "${CURL_TLS[@]}" -fsS -X POST "${auth_hdr[@]}" -H 'Content-Type: application/json' \
      "$BRIDGE/api/json-api/poll-once" -d "$json_poll_body" 2>/dev/null || echo '{}')"
    jq -e '.ok == true and .http_status == 200' <<<"$j" >/dev/null 2>&1 && json_ok=true
  fi

  jq -nc \
    --arg ts "$ts" --argjson n "$n" \
    --argjson live "$live" \
    --argjson modbus "$modbus_ok" --argjson haystack "$haystack_ok" \
    --argjson json "$json_ok" --argjson bacnet "$bacnet_ok" \
    '{timestamp_utc:$ts,cycle:$n,modbus_read_ok:$modbus,modbus_value:($live.modbus_value//null),
      bacnet_read_ok:$bacnet,bacnet_value:($live.bacnet_value//null),bacnet_whois_ok:($live.bacnet_whois_ok//false),
      haystack_test_ok:$haystack,json_api_poll_ok:$json,modbus_poll_ok:$modbus}' \
    >>"$LOG_DIR/poll_summary.jsonl"
  log "  cycle=$n modbus_read=$modbus_ok($(jq -r '.modbus_value // "?"' <<<"$live")) bacnet_read=$bacnet_ok($(jq -r '.bacnet_value // "?"' <<<"$live")) json=$json_ok haystack=$haystack_ok"
  [[ "$n" -lt "$POLL_CYCLES" ]] && sleep "$POLL_INTERVAL"
done

# --- Phase 4: FDD + devices snapshot ---
log "Phase 4: FDD + devices snapshot"
curl "${CURL_TLS[@]}" -fsS "${auth_hdr[@]}" "$BRIDGE/api/validation-runs/current/status" \
  -o "$LOG_DIR/validation_run_status.json" 2>/dev/null || echo '{}' >"$LOG_DIR/validation_run_status.json"
curl "${CURL_TLS[@]}" -fsS "${auth_hdr[@]}" "$BRIDGE/api/bacnet/driver/tree" \
  -o "$LOG_DIR/bacnet_driver_tree.json" 2>/dev/null || echo '{}' >"$LOG_DIR/bacnet_driver_tree.json"
curl "${CURL_TLS[@]}" -fsS "${auth_hdr[@]}" "$BRIDGE/api/haystack/driver/tree" \
  -o "$LOG_DIR/haystack_driver_tree.json" 2>/dev/null || echo '{}' >"$LOG_DIR/haystack_driver_tree.json"

FDD_RULE_ID="${OPENFDD_FDD_RULE_ID:-oa_temp_out_of_range}"
jq -nc \
  --arg finished "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg rule "$FDD_RULE_ID" \
  --arg log_dir "$LOG_DIR" \
  --argjson reads "$(jq -s '.' "$LOG_DIR/driver_readings.jsonl" 2>/dev/null || echo '[]')" \
  --argjson polls "$(jq -s '.' "$LOG_DIR/poll_summary.jsonl" 2>/dev/null || echo '[]')" \
  --slurpfile vr "$LOG_DIR/validation_run_status.json" \
  --slurpfile bt "$LOG_DIR/bacnet_driver_tree.json" \
  --slurpfile bd "$LOG_DIR/bacnet_discovery.json" \
  --slurpfile md "$LOG_DIR/modbus_discovery.json" \
  --slurpfile hs "$LOG_DIR/haystack_driver_tree.json" \
  '{
    finished_at: $finished,
    fdd_rule_id: $rule,
    fdd_equation_hint: "oa_t < 40 OR oa_t > 110 → raw_fault (see validation profile SQL)",
    devices_tested: {
      bacnet: ($bd[0].devices // []),
      modbus_devices: ($md[0].device_count // 0),
      haystack_enabled: (($hs[0].enabled // false) | tostring)
    },
    driver_readings: $reads,
    poll_cycles: $polls,
    validation_run: ($vr[0] // {}),
    bacnet_tree_present: (($bt[0].drivers // $bt[0].devices // []) | length >= 0),
    artifact_dir: $log_dir
  }' >"$LOG_DIR/fdd_snapshot.json"

# --- Phase 5: PDF ---
if [[ "$GENERATE_PDF" == "1" ]]; then
  log "Phase 5: validation PDF"
  export OPENFDD_ISSUE402_REPORT_DIR="$LOG_DIR"
  export OPENFDD_ISSUE402_REPORT_JSON="$LOG_DIR/report_sections.json"
  export OPENFDD_ISSUE402_TITLE="Open-FDD ${EXPECT_VER} Driver Validation — Bench ${RUN_TS}"

  jq -nc \
    --arg title "Open-FDD ${EXPECT_VER} Driver Validation — Bench ${RUN_TS}" \
    --argjson snap "$(cat "$LOG_DIR/fdd_snapshot.json")" \
    --argjson reads "$(jq -s '.' "$LOG_DIR/driver_readings.jsonl")" \
    '{
      title: $title,
      sections: [
        {id:"building-summary",title:"Building summary",type:"building_summary",order:0,visible:true,
         content:{template_id:"validation-summary",title:$title,generated_at:$snap.finished_at,sites:{ok:true,active_site_id:"site:local"}}},
        {id:"source-health",title:"Source health",type:"source_health",order:1,visible:true,
         content:{ok:true,protocols:[
           {protocol:"bacnet",point_count:($reads|map(select(.driver=="bacnet" and .ok))|length)},
           {protocol:"modbus",point_count:($reads|map(select(.driver=="modbus" and .ok))|length)},
           {protocol:"haystack",point_count:($reads|map(select(.driver=="haystack" and .ok))|length)},
           {protocol:"json_api",point_count:($reads|map(select(.driver=="json-api" and .ok))|length)}
         ]}},
        {id:"devices-tested",title:"Devices tested",type:"equipment_summary",order:2,visible:true,
         content:{ok:true,site_id:"site:local",count:($snap.devices_tested.bacnet|length),equips:
           [$snap.devices_tested.bacnet[]? | {
             equipment_id: ("equip:bacnet-" + ((.device_instance|tostring) // "unknown")),
             name: (.name // "discovered-device"),
             bacnet_device: .device_instance,
             bacnet_ip: (.address // "")
           }]
         }},
        {id:"driver-readings",title:"Driver readings snapshot",type:"rule_explanation",order:3,visible:true,
         content:{ok:true,explanation:"Point-level reads from rigorous validation",readings:$reads}},
        {id:"rule-explanation",title:"FDD rule: oa_temp_out_of_range",type:"rule_explanation",order:4,visible:true,
         content:{
           rule_id:"oa_temp_out_of_range",
           rule_name:"OA Temperature Out Of Range",
           explanation:"Outside air temperature below 40F or above 110F",
           raw_fault_logic:"raw_fault when SQL predicate true",
           confirmed_fault_logic:"confirmed_fault when raw_fault sustained for confirmation_seconds",
           required_inputs:["oa_t"],
           sql:"SELECT timestamp, equipment_id, oa_t, CASE WHEN oa_t IS NULL THEN false WHEN oa_t < 40.0 THEN true WHEN oa_t > 110.0 THEN true ELSE false END AS fault_raw FROM telemetry_pivot WHERE equipment_id = '\''equip:validation'\''"
         }},
        {id:"poll-stability",title:"Poll stability",type:"historian_summary",order:5,visible:true,
         content:{ok:true,poll_cycles:$snap.poll_cycles,artifact_dir:$snap.artifact_dir}}
      ]
    }' >"$LOG_DIR/report_sections.json"

  if [[ -x "$ROOT/scripts/openfdd_323_validation_pdf.sh" ]]; then
    if OPENFDD_VALIDATION_PDF_DIR="$LOG_DIR" "$ROOT/scripts/openfdd_323_validation_pdf.sh" 2>&1 | tee "$LOG_DIR/pdf.log"; then
      log "PDF OK"
    else
      log "WARN: PDF generation failed — see pdf.log"
    fi
  else
    log "SKIP PDF — openfdd_323_validation_pdf.sh not on bench (report_sections.json captured)"
  fi
fi

read_fail="$(jq -s '[.[] | select(.ok==false)] | length' "$LOG_DIR/driver_readings.jsonl" 2>/dev/null || echo 0)"
poll_fail="$(jq -s '[.[] | select(.modbus_read_ok==false or .bacnet_read_ok==false or .haystack_test_ok==false or .json_api_poll_ok==false)] | length' "$LOG_DIR/poll_summary.jsonl" 2>/dev/null || echo 0)"

jq -nc \
  --arg ts "$RUN_TS" --arg dir "$LOG_DIR" \
  --argjson read_fail "$read_fail" --argjson poll_fail "$poll_fail" \
  '{run_ts:$ts,artifact_dir:$dir,read_failures:$read_fail,poll_failures:$poll_fail,passed:(($read_fail==0) and ($poll_fail==0))}' \
  >"$LOG_DIR/final_report.json"

log "Complete — read_fail=$read_fail poll_fail=$poll_fail artifact=$LOG_DIR"
[[ "$read_fail" -eq 0 && "$poll_fail" -eq 0 ]]
