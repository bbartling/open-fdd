#!/usr/bin/env bash
# Gate 20 — Wave I app-test MEGAs (basic app + dual OAT + plot span).
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
record() {
  local id="$1" ok="$2" detail="$3"
  echo "$id ok=$ok $detail" | tee -a "$LOG"
  [[ "$ok" == "1" ]] || FAIL=1
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

# 2) Data model mapping for MQTT bldg2
body="$(cget "/api/csv/import/package/mapping?building_id=bldg2")"
echo "$body" >"$ART/wave_i_mapping_bldg2.json"
eq_n="$(echo "$body" | jq -r '(.equipment // []) | length' 2>/dev/null || echo 0)"
ok_map="$(echo "$body" | jq -r '.ok // false' 2>/dev/null || echo false)"
if [[ "$ok_map" == "true" && "$eq_n" =~ ^[0-9]+$ && "$eq_n" -gt 0 ]]; then
  record mapping_bldg2 1 "equipment=$eq_n"
else
  record mapping_bldg2 0 "ok=$ok_map equipment=$eq_n"
fi

# 3) Inspect bldg2 zone_t
body="$(cpost /api/analytics/inspect '{"building_id":"bldg2","equipment_ids":["bldg2-zone-loopback"],"max_points":800,"series":{"columns":["zone_t"]}}')"
echo "$body" >"$ART/wave_i_inspect_bldg2.json"
zt="$(echo "$body" | python3 -c 'import json,sys
a=(json.load(sys.stdin).get("analytics") or {})
pts=a.get("points") or []
print(sum(1 for p in pts if p.get("zone_t") is not None))')"
if [[ "${zt:-0}" -gt 0 ]]; then
  record inspect_zone_t 1 "non_null=$zt"
else
  record inspect_zone_t 0 "non_null=$zt"
fi

# 4) bas-vs-web bldg2 (requires dual-OAT catalog + soak)
body="$(cpost /api/analytics/bas-vs-web-oat '{"building_id":"bldg2","max_points":2000}')"
echo "$body" >"$ART/wave_i_bas_vs_web_bldg2.json"
pts="$(echo "$body" | jq -r '(.analytics.points // []) | length' 2>/dev/null || echo 0)"
if [[ "${pts:-0}" -gt 0 ]]; then
  record bas_vs_web_bldg2 1 "points=$pts"
else
  record bas_vs_web_bldg2 0 "points=0"
fi

# 5) B100 inspect — plotted span vs coverage (even downsample)
body="$(cpost /api/analytics/inspect '{"building_id":"BUILDING_100","max_points":2000}')"
echo "$body" >"$ART/wave_i_inspect_b100.json"
span_ok="$(echo "$body" | python3 -c '
import json,sys
from datetime import datetime
a=(json.load(sys.stdin).get("analytics") or {})
cov=a.get("coverage") or {}
pts=a.get("points") or []
def parse(s):
  if not s: return None
  s=str(s).replace("Z","+00:00")
  try: return datetime.fromisoformat(s)
  except Exception: return None
cf,cl=parse(cov.get("first_timestamp")),parse(cov.get("last_timestamp"))
if not pts or not cf or not cl:
  print(0); raise SystemExit
ts=[parse(p.get("timestamp_utc")) for p in pts]
ts=[t for t in ts if t]
if len(ts)<2:
  print(0); raise SystemExit
pf,pl=min(ts),max(ts)
cov_days=(cl-cf).total_seconds()/86400.0
plot_days=(pl-pf).total_seconds()/86400.0
print(1 if cov_days < 14 or plot_days >= 0.5 * cov_days else 0)
')"
if [[ "${span_ok:-0}" == "1" ]]; then
  record b100_plot_span 1 "ok"
else
  record b100_plot_span 0 "plot span << coverage"
fi

jq -n --argjson fail "$FAIL" '{gate:"20_wave_i_app_test_megas", fail:$fail}' \
  >"$ART/wave_i_app_test_megas.json"

if [[ "$FAIL" -eq 0 ]]; then
  ok "Wave I app-test MEGAs PASS"
  exit 0
fi
bad "Wave I app-test MEGAs FAIL — see $LOG"
exit 1
