#!/usr/bin/env bash
# Gate 21 — Wave K app-test MEGAs (sensor-faults + MQTT quad + data-model).
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
LOG="$ART/wave_k_app_test_megas.log"
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
# Missing historian roles (AV9101/9102 not published) stay field-catalog Soft-OPEN.
# A present column with no values is a product fail. Soft-OPEN is not a PASS.
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

# 1) Lakeside sensor-faults matrix discovers historian equipment
body="$(cpost /api/analytics/sensor-faults '{"building_id":"LAKESIDE_ES"}')"
echo "$body" >"$ART/wave_k_sensor_faults_lakeside.json"
matched="$(echo "$body" | jq -r '.analytics.coverage.matched_equipment_count // .coverage.matched_equipment_count // 0')"
rows="$(echo "$body" | jq -r '(.analytics.rows // .rows // []) | length')"
if [[ "${matched:-0}" -gt 0 && "${rows:-0}" -gt 0 ]]; then
  record sensor_faults_lakeside 1 "matched=$matched rows=$rows"
else
  record sensor_faults_lakeside 0 "matched=$matched rows=$rows"
fi

# 2) MQTT quad — recent loopback has zone_t + oa_t + zone_rh; hosted-weather web_oa_t.
# Absent columns stay field-catalog Soft-OPEN. A present column with no values is a product fail.
payload="$(jq -nc --arg b "$MQTT_BUILDING" --arg e "$LOOPBACK_EQ" \
  '{building_id:$b, equipment_ids:[$e], max_points:200}')"
body="$(cpost /api/analytics/inspect "$payload")"
echo "$body" >"$ART/wave_k_inspect_loopback.json"
# Single-quoted python -c: use "…" for JSON keys (\" breaks under bash $'…' / eval).
eval "$(echo "$body" | python3 -c '
import json,sys
a=(json.load(sys.stdin).get("analytics") or {})
cov=a.get("coverage") or {}
plot=set(cov.get("plottable_columns") or [])
pts=a.get("points") or []
def n(k): return sum(1 for p in pts if p.get(k) is not None)
def has(k): return 1 if k in plot else 0
print("zt=%d" % n("zone_t"))
print("oa=%d" % n("oa_t"))
print("rh=%d" % n("zone_rh"))
print("n=%d" % len(pts))
print("zone_col=%d" % has("zone_t"))
print("oa_col=%d" % has("oa_t"))
print("rh_col=%d" % has("zone_rh"))
')"
if [[ "${zt:-0}" -gt 0 && "${oa:-0}" -gt 0 ]]; then
  record mqtt_zone_and_oa 1 "zone_t=$zt oa_t=$oa n=$n"
elif [[ "${zone_col:-0}" == "1" && "${oa_col:-0}" == "1" ]]; then
  record mqtt_zone_and_oa 0 "columns present zone_t=$zt oa_t=$oa n=$n"
else
  record_soft mqtt_zone_and_oa "zone_t/oa_t column absent zone_t=${zt:-0} oa_t=${oa:-0} n=${n:-0}"
fi
if [[ "${rh:-0}" -gt 0 ]]; then
  record mqtt_zone_rh 1 "zone_rh=$rh"
elif [[ "${rh_col:-0}" == "1" ]]; then
  record mqtt_zone_rh 0 "zone_rh column present value=0"
else
  record_soft mqtt_zone_rh "zone_rh column absent (fieldbus tip + AV9102)"
fi

payload="$(jq -nc --arg b "$MQTT_BUILDING" --arg e "$WEATHER_EQ" \
  '{building_id:$b, equipment_ids:[$e], max_points:50}')"
body="$(cpost /api/analytics/inspect "$payload")"
echo "$body" >"$ART/wave_k_inspect_hosted_weather.json"
eval "$(echo "$body" | python3 -c '
import json,sys
a=(json.load(sys.stdin).get("analytics") or {})
cov=a.get("coverage") or {}
plot=set(cov.get("plottable_columns") or [])
pts=a.get("points") or []
print("web=%d" % sum(1 for p in pts if p.get("web_oa_t") is not None))
print("web_col=%d" % (1 if "web_oa_t" in plot else 0))
')"
if [[ "${web:-0}" -gt 0 ]]; then
  record mqtt_web_oa_t 1 "web_oa_t=$web"
elif [[ "${web_col:-0}" == "1" ]]; then
  record mqtt_web_oa_t 0 "web_oa_t column present value=0"
else
  record_soft mqtt_web_oa_t "web_oa_t column absent"
fi

# 3) Data model — ACME historian roles non-empty; wrong-site eq fails closed
body="$(cget "/api/csv/import/package/mapping?building_id=$(urlencode "$MQTT_BUILDING")")"
echo "$body" >"$ART/wave_k_mapping_acme.json"
cols="$(echo "$body" | python3 -c '
import json,sys
d=json.load(sys.stdin)
eqs=d.get("equipment") or []
n=0
for e in eqs:
  n=max(n, len(e.get("columns") or []), len(e.get("roles") or {}))
print(n)
')"
if [[ "${cols:-0}" -gt 0 ]]; then
  record mapping_acme_roles 1 "building=$MQTT_BUILDING max_columns=$cols"
else
  record mapping_acme_roles 0 "building=$MQTT_BUILDING max_columns=$cols"
fi

body="$(cget "/api/csv/import/package/mapping?building_id=BUILDING_100&equipment_id=$(urlencode "$LOOPBACK_EQ")")"
echo "$body" >"$ART/wave_k_mapping_cross_site.json"
# jq `false // true` yields true — do not use // for boolean .ok
ok_cross="$(echo "$body" | jq -r '.ok')"
err_cross="$(echo "$body" | jq -r '.error // empty')"
if [[ "$ok_cross" == "false" && -n "$err_cross" ]]; then
  record mapping_cross_site 1 "fail_closed"
else
  record mapping_cross_site 0 "ok=$ok_cross error=${err_cross:-none}"
fi

jq -n --argjson fail "$FAIL" --argjson product "$PRODUCT" --argjson soft "$SOFT" \
  '{gate:"21_wave_k_app_test_megas", fail:$fail, product_fail:$product, field_catalog_soft_open:$soft}' \
  >"$ART/wave_k_app_test_megas.json"

if [[ "$FAIL" -eq 0 ]]; then
  ok "Wave K app-test MEGAs PASS"
  exit 0
fi
if [[ "$PRODUCT" -eq 0 && "$SOFT" -gt 0 ]]; then
  bad "Wave K product checks passed; field-catalog Soft-OPEN (not a product PASS, not FQ) — see $LOG"
else
  bad "Wave K app-test MEGAs FAIL — see $LOG"
fi
exit 1
