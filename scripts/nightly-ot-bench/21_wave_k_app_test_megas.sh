#!/usr/bin/env bash
# Gate 21 — Wave K app-test MEGAs (sensor-faults + MQTT quad + data-model).
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
record() {
  local id="$1" ok="$2" detail="$3"
  echo "$id ok=$ok $detail" | tee -a "$LOG"
  [[ "$ok" == "1" ]] || FAIL=1
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

# 2) MQTT quad — recent loopback has zone_t + oa_t + zone_rh; hosted-weather web_oa_t
body="$(cpost /api/analytics/inspect '{"building_id":"bldg2","equipment_ids":["bldg2-zone-loopback"],"max_points":200}')"
echo "$body" >"$ART/wave_k_inspect_loopback.json"
# Single-quoted python -c: use "…" for JSON keys (\" breaks under bash $'…' / eval).
eval "$(echo "$body" | python3 -c '
import json,sys
a=(json.load(sys.stdin).get("analytics") or {})
pts=a.get("points") or []
def n(k): return sum(1 for p in pts if p.get(k) is not None)
print("zt=%d" % n("zone_t"))
print("oa=%d" % n("oa_t"))
print("rh=%d" % n("zone_rh"))
print("n=%d" % len(pts))
')"
if [[ "${zt:-0}" -gt 0 && "${oa:-0}" -gt 0 ]]; then
  record mqtt_zone_and_oa 1 "zone_t=$zt oa_t=$oa n=$n"
else
  record mqtt_zone_and_oa 0 "zone_t=$zt oa_t=$oa n=$n"
fi
if [[ "${rh:-0}" -gt 0 ]]; then
  record mqtt_zone_rh 1 "zone_rh=$rh"
else
  record mqtt_zone_rh 0 "zone_rh=$rh (need fieldbus tip + AV9102 soak)"
fi

body="$(cpost /api/analytics/inspect '{"building_id":"bldg2","equipment_ids":["hosted-weather"],"max_points":50}')"
echo "$body" >"$ART/wave_k_inspect_hosted_weather.json"
web="$(echo "$body" | python3 -c 'import json,sys; a=(json.load(sys.stdin).get("analytics") or {}); pts=a.get("points") or []; print(sum(1 for p in pts if p.get("web_oa_t") is not None))')"
if [[ "${web:-0}" -gt 0 ]]; then
  record mqtt_web_oa_t 1 "web_oa_t=$web"
else
  record mqtt_web_oa_t 0 "web_oa_t=$web"
fi

# 3) Data model — bldg2 historian roles non-empty; wrong-site eq fails closed
body="$(cget "/api/csv/import/package/mapping?building_id=bldg2")"
echo "$body" >"$ART/wave_k_mapping_bldg2.json"
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
  record mapping_bldg2_roles 1 "max_columns=$cols"
else
  record mapping_bldg2_roles 0 "max_columns=$cols"
fi

body="$(cget "/api/csv/import/package/mapping?building_id=BUILDING_100&equipment_id=bldg2-zone-loopback")"
echo "$body" >"$ART/wave_k_mapping_cross_site.json"
# jq `false // true` yields true — do not use // for boolean .ok
ok_cross="$(echo "$body" | jq -r '.ok')"
err_cross="$(echo "$body" | jq -r '.error // empty')"
if [[ "$ok_cross" == "false" && -n "$err_cross" ]]; then
  record mapping_cross_site 1 "fail_closed"
else
  record mapping_cross_site 0 "ok=$ok_cross error=${err_cross:-none}"
fi

jq -n --argjson fail "$FAIL" '{gate:"21_wave_k_app_test_megas", fail:$fail}' \
  >"$ART/wave_k_app_test_megas.json"

if [[ "$FAIL" -eq 0 ]]; then
  ok "Wave K app-test MEGAs PASS"
  exit 0
fi
bad "Wave K app-test MEGAs FAIL — see $LOG"
exit 1
