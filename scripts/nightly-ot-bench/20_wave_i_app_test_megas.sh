#!/usr/bin/env bash
# Gate 20 — Wave I app-test MEGAs (basic app + dual OAT + plot span).
# Live MQTT building is ACME (edges vim-1 / pi-1). `bldg2` is not a building id.
# Loopback / hosted-weather equipment ids are unchanged. Missing AV columns stay Soft-OPEN.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib.sh"
load_bench_env
cd "$ROOT"

ART="${ARTIFACT_DIR:-$(artifact_dir)}"
mkdir -p "$ART"
LOG="$ART/wave_i_app_test_megas.log"
: >"$LOG"

central_auth_setup
cpost() {
  local path="$1" body="$2"
  curl -sS --max-time 120 "${CENTRAL_AUTH_HDR[@]+"${CENTRAL_AUTH_HDR[@]}"}" \
    -H 'Content-Type: application/json' -d "$body" \
    "$CENTRAL_BASE$path"
}
cget() {
  curl -sS --max-time 60 "${CENTRAL_AUTH_HDR[@]+"${CENTRAL_AUTH_HDR[@]}"}" \
    "$CENTRAL_BASE$1"
}

FAIL=0
PRODUCT=0
SOFT=0
record() {
  local id="$1" ok="$2" detail="$3"
  echo "$id ok=$ok $detail" | tee -a "$LOG"
  if [[ "$ok" != "1" ]]; then
    FAIL=1
    PRODUCT=1
  fi
}
# Field catalog (AV not in the historian) stays Soft-OPEN. It is not a product
# PASS and it still fails this required gate so fully_qualified stays false.
record_soft() {
  local id="$1" detail="$2"
  echo "$id ok=0 soft_open=1 field_catalog $detail" | tee -a "$LOG"
  FAIL=1
  SOFT=$((SOFT + 1))
}

# Override with OPENFDD_WAVE_MQTT_BUILDING when the hub site id is not ACME.
MQTT_BUILDING="${OPENFDD_WAVE_MQTT_BUILDING:-ACME}"
LOOPBACK_EQ="${OPENFDD_WAVE_MQTT_LOOPBACK_EQ:-bldg2-zone-loopback}"
WEATHER_EQ="${OPENFDD_WAVE_MQTT_WEATHER_EQ:-hosted-weather}"
urlencode() {
  python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=""))' "$1"
}

# 1) Lakeside FC1 — must not hit read_csv planning error
body="$(cpost /api/fdd/run '{"building_id":"LAKESIDE_ES","rule_ids":["FC1"]}')"
echo "$body" >"$ART/wave_i_lakeside_fc1.json"
if echo "$body" | grep -qi 'read_csv'; then
  record lakeside_fc1 0 "contains read_csv"
elif echo "$body" | jq -e '(.error // "" | tostring | test("read_csv"; "i"))' >/dev/null 2>&1; then
  record lakeside_fc1 0 "error mentions read_csv"
else
  record lakeside_fc1 1 "no read_csv planning error"
fi

# 2) Data model mapping for the live MQTT building (ACME).
body="$(cget "/api/csv/import/package/mapping?building_id=$(urlencode "$MQTT_BUILDING")")"
echo "$body" >"$ART/wave_i_mapping_acme.json"
eq_n="$(echo "$body" | jq -r '(.equipment // []) | length' 2>/dev/null || echo 0)"
ok_map="$(echo "$body" | jq -r '.ok // false' 2>/dev/null || echo false)"
has_loop="$(echo "$body" | jq -r --arg e "$LOOPBACK_EQ" '([.equipment_ids[]?, .equipment[]?.equipment_id] | index($e) != null)')"
has_wx="$(echo "$body" | jq -r --arg e "$WEATHER_EQ" '([.equipment_ids[]?, .equipment[]?.equipment_id] | index($e) != null)')"
if [[ "$ok_map" == "true" && "$eq_n" =~ ^[0-9]+$ && "$eq_n" -gt 0 && "$has_loop" == "true" && "$has_wx" == "true" ]]; then
  record mapping_acme 1 "building=$MQTT_BUILDING equipment=$eq_n"
else
  record mapping_acme 0 "building=$MQTT_BUILDING ok=$ok_map equipment=$eq_n loopback=$has_loop weather=$has_wx"
fi

# 3) Inspect ACME loopback zone_t. Absent column is field-catalog Soft-OPEN.
payload="$(jq -nc --arg b "$MQTT_BUILDING" --arg e "$LOOPBACK_EQ" \
  '{building_id:$b, equipment_ids:[$e], max_points:800, series:{columns:["zone_t"]}}')"
body="$(cpost /api/analytics/inspect "$payload")"
echo "$body" >"$ART/wave_i_inspect_zone_t.json"
eval "$(echo "$body" | python3 -c '
import json,sys
a=(json.load(sys.stdin).get("analytics") or {})
cov=a.get("coverage") or {}
plot=set(cov.get("plottable_columns") or [])
pts=a.get("points") or []
zt=sum(1 for p in pts if p.get("zone_t") is not None)
print("zt=%d" % zt)
print("zone_col=%d" % (1 if "zone_t" in plot else 0))
')"
if [[ "${zt:-0}" -gt 0 ]]; then
  record inspect_zone_t 1 "non_null=$zt"
elif [[ "${zone_col:-0}" == "1" ]]; then
  record inspect_zone_t 0 "zone_t column present non_null=${zt:-0}"
else
  record_soft inspect_zone_t "zone_t column absent non_null=${zt:-0}"
fi

# 4) bas-vs-web on the live MQTT building (requires dual-OAT catalog + soak)
payload="$(jq -nc --arg b "$MQTT_BUILDING" '{building_id:$b, max_points:2000}')"
body="$(cpost /api/analytics/bas-vs-web-oat "$payload")"
echo "$body" >"$ART/wave_i_bas_vs_web_acme.json"
eval "$(echo "$body" | python3 -c '
import json,sys
body=json.load(sys.stdin)
a=body.get("analytics") or {}
pts=len(a.get("points") or [])
warns=" ".join(str(w) for w in (a.get("warnings") or [])).lower()
missing=1 if ("unavailable" in warns or "need distinct" in warns) else 0
print("pts=%d" % pts)
print("missing_roles=%d" % missing)
')"
if [[ "${pts:-0}" -gt 0 ]]; then
  record bas_vs_web_acme 1 "building=$MQTT_BUILDING points=$pts"
elif [[ "${missing_roles:-0}" == "1" ]]; then
  record_soft bas_vs_web_acme "building=$MQTT_BUILDING oa_t/web_oa_t columns absent points=0"
else
  record bas_vs_web_acme 0 "building=$MQTT_BUILDING points=0 roles_present"
fi

# 5) B100 inspect — span-preserving downsample (equipment_id required; AHU_1).
# Require multi-month plot span so ORDER BY…LIMIT July-only truncation fails the gate.
# (coverage first/last currently mirror plotted points — do not treat them as historian truth.)
body="$(cpost /api/analytics/inspect '{"building_id":"BUILDING_100","equipment_ids":["AHU_1"],"max_points":2000}')"
echo "$body" >"$ART/wave_i_inspect_b100.json"
eval "$(echo "$body" | python3 -c '
import json,sys
from datetime import datetime
a=(json.load(sys.stdin).get("analytics") or {})
pts=a.get("points") or []
def parse(s):
  if not s: return None
  s=str(s).replace("Z","+00:00")
  try: return datetime.fromisoformat(s)
  except Exception: return None
ts=[parse(p.get("timestamp_utc")) for p in pts]
ts=[t for t in ts if t]
if len(ts)<2:
  print("span_ok=0")
  print("plot_detail=points=0")
  raise SystemExit
days=(max(ts)-min(ts)).total_seconds()/86400.0
# BUILDING_100 package spans ~Mar–Jul; July-only truncation is ~<=35d.
print(f"span_ok={1 if days >= 60.0 else 0}")
print(f"plot_detail=points={len(ts)}_plot_days={days:.1f}")
')"
if [[ "${span_ok:-0}" == "1" ]]; then
  record b100_plot_span 1 "${plot_detail:-ok}"
else
  record b100_plot_span 0 "${plot_detail:-plot span too short}"
fi

jq -n --argjson fail "$FAIL" --argjson product "$PRODUCT" --argjson soft "$SOFT" \
  '{gate:"20_wave_i_app_test_megas", fail:$fail, product_fail:$product, field_catalog_soft_open:$soft}' \
  >"$ART/wave_i_app_test_megas.json"

if [[ "$FAIL" -eq 0 ]]; then
  ok "Wave I app-test MEGAs PASS"
  exit 0
fi
if [[ "$PRODUCT" -eq 0 && "$SOFT" -gt 0 ]]; then
  bad "Wave I product checks passed; field-catalog Soft-OPEN (not a product PASS, not FQ) — see $LOG"
else
  bad "Wave I app-test MEGAs FAIL — see $LOG"
fi
exit 1
