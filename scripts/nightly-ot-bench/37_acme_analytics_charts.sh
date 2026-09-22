#!/usr/bin/env bash
# Gate 37 — ACME Overview / charts analytics sequential break-finder.
#
# Hits the same POST /api/analytics/* surface the React Overview + RCx/health
# panels use, one at a time, as the ACME tenant operator. Hard-fails on the
# first 502/503/504/timeout (nginx Bad Gateway) and records which probe broke.
# Re-checks /api/health after each call so a crash is distinguished from a
# single-route hang.
#
# Why separate from 24_capacity_pressure:
# - Gate 24 picks a building + one FDD/run; UI charts fire many analytics POSTs.
# - Agent JWT is hub-scoped and gets 403 on ACME under MT; UI uses acme-ops.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib.sh"
load_bench_env
cd "$ROOT"

ART="${ARTIFACT_DIR:-$(artifact_dir)}"
mkdir -p "$ART"
export ARTIFACT_DIR="$ART"
export OPENFDD_STRESS_GATE="37_acme_analytics_charts"
LOG="$ART/37_acme_analytics_charts.log"
: >"$LOG"
SUMMARY="$ART/37_acme_analytics_charts_summary.json"

if [[ "${RAILWAY_ONLY:-0}" != "1" && "${ACME_ANALYTICS_CHARTS:-0}" != "1" ]]; then
  echo "SKIP: set RAILWAY_ONLY=1 or ACME_ANALYTICS_CHARTS=1" | tee -a "$LOG"
  exit 0
fi

BASE="${OPENFDD_API_BASE:-${CENTRAL_BASE:-}}"
BUILDING="${OPENFDD_ACME_ANALYTICS_BUILDING:-ACME}"
USER_NAME="${OPENFDD_USER_A_OPS_USER:-acme-ops}"
PASS="${OPENFDD_USER_ACME_OPS_PASSWORD:-${OPENFDD_USER_A_OPS_PASSWORD:-${OPENFDD_OPS_A_PASSWORD:-}}}"

# Optional Railway refresh (never print values).
if [[ -z "$PASS" ]] && command -v railway >/dev/null 2>&1; then
  _tmp="$(mktemp)"
  if env -u RAILWAY_TOKEN railway variable list \
    --service "${OPENFDD_RAILWAY_CENTRAL_SVC:-openfdd-central-cQ-F}" --json >"$_tmp" 2>/dev/null; then
    PASS="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("OPENFDD_USER_ACME_OPS_PASSWORD","") or "")' "$_tmp")"
  fi
  rm -f "$_tmp"
fi

if [[ -z "$BASE" || -z "$PASS" ]]; then
  echo "FAIL: need OPENFDD_API_BASE and ACME ops password (OPENFDD_USER_ACME_OPS_PASSWORD)" | tee -a "$LOG"
  exit 1
fi

login_json="$ART/37_login.json"
login_code="$(curl -sS -o "$login_json" -w '%{http_code}' --max-time 30 \
  -X POST "$BASE/api/auth/login" \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg u "$USER_NAME" --arg p "$PASS" '{username:$u,password:$p}')")"
TOK="$(jq -r '.token // .access_token // empty' "$login_json" 2>/dev/null || true)"
# Redact token from on-disk login artifact.
jq 'del(.token,.access_token) | .token_present=(.token!=null or .access_token!=null)' \
  "$login_json" >"$login_json.tmp" 2>/dev/null || echo '{}' >"$login_json.tmp"
mv "$login_json.tmp" "$login_json"
if [[ "$login_code" != "200" || -z "$TOK" ]]; then
  echo "FAIL: $USER_NAME login HTTP $login_code" | tee -a "$LOG"
  exit 1
fi
echo "login ok user=$USER_NAME" | tee -a "$LOG"

health_ok() {
  local h
  h="$(curl -sf --max-time 20 "$BASE/api/health" || echo '{}')"
  echo "$h" >"$ART/37_health_latest.json"
  echo "$h" | jq -e '.ok == true' >/dev/null 2>&1
}

if ! health_ok; then
  echo "FAIL: central /api/health not ok before probes" | tee -a "$LOG"
  exit 1
fi
echo "health ok before probes version=$(jq -r '.version // empty' "$ART/37_health_latest.json")" | tee -a "$LOG"

# Confirm package inventory for ACME (light).
eq_body="$ART/37_equipment.json"
eq_code="$(curl -sS -o "$eq_body" -w '%{http_code}' --max-time 60 \
  -H "Authorization: Bearer $TOK" \
  "$BASE/api/fdd/equipment?building_id=$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))' "$BUILDING")")"
echo "equipment HTTP $eq_code" | tee -a "$LOG"
if [[ "$eq_code" == "502" || "$eq_code" == "503" || "$eq_code" == "504" || "$eq_code" == "000" ]]; then
  echo "FAIL: equipment list HTTP $eq_code (nginx/central unavailable)" | tee -a "$LOG"
  exit 1
fi
if [[ "$eq_code" != "200" ]]; then
  echo "FAIL: equipment list HTTP $eq_code (ACME package / ACL?)" | tee -a "$LOG"
  exit 1
fi
EQ_N="$(python3 - "$eq_body" <<'PY'
import json,sys
from pathlib import Path
b=json.loads(Path(sys.argv[1]).read_text())
eq=b.get("equipment") or b.get("equipment_ids") or b.get("items") or []
if isinstance(b, list): eq=b
print(len(eq) if isinstance(eq,list) else 0)
PY
)"
echo "equipment_n=$EQ_N building=$BUILDING" | tee -a "$LOG"
if [[ "$EQ_N" -lt 1 ]]; then
  echo "FAIL: ACME has no equipment — package not loaded or empty inventory" | tee -a "$LOG"
  exit 1
fi

# Pick a representative AHU for inspect/series-style bodies.
AHU_ID="$(python3 - "$eq_body" <<'PY'
import json,sys
from pathlib import Path
b=json.loads(Path(sys.argv[1]).read_text())
eq=b.get("equipment") or b.get("items") or []
ids=[]
for e in eq if isinstance(eq,list) else []:
    if isinstance(e,str): ids.append(e)
    elif isinstance(e,dict):
        eid=e.get("equipment_id") or e.get("id") or e.get("name")
        if eid: ids.append(str(eid))
prefer=[i for i in ids if "AHU" in i.upper() or "RTU" in i.upper()]
print((prefer or ids or [""])[0])
PY
)"
echo "ahu_id=${AHU_ID:-none}" | tee -a "$LOG"

# Sequential Overview / charts matrix (UI-shaped). One at a time — do not
# parallelize; concurrent agent probes can themselves trip nginx 502s.
HARD_TIMEOUT="${ACME_ANALYTICS_HARD_TIMEOUT_SECS:-180}"
PROBES_FILE="$ART/37_probes.jsonl"
: >"$PROBES_FILE"

# Overview-shaped lookback (matches SPA). Unbounded runtime LEAD times out on ACME.
START_ISO="$(python3 -c 'from datetime import datetime,timedelta,timezone; print((datetime.now(timezone.utc)-timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ"))')"

probe() {
  local name="$1" method="$2" path="$3" body="${4:-}"
  local out="$ART/37_probe_${name}.json"
  local code elapsed start end curl_rc
  local settle="${ANALYTICS_SETTLE_SECS:-45}"
  local attempt=0
  local max_attempts=2

  while true; do
    attempt=$((attempt + 1))
    start="$(date +%s)"
    set +e
    if [[ "$method" == "GET" ]]; then
      code="$(curl -sS -o "$out" -w '%{http_code}' --max-time "$HARD_TIMEOUT" \
        -H "Authorization: Bearer $TOK" "$BASE$path")"
    else
      code="$(curl -sS -o "$out" -w '%{http_code}' --max-time "$HARD_TIMEOUT" \
        -X POST -H "Authorization: Bearer $TOK" -H 'Content-Type: application/json' \
        -d "$body" "$BASE$path")"
    fi
    curl_rc=$?
    set -e
    end="$(date +%s)"
    elapsed=$((end - start))
    # curl timeout/connect fail → empty or 000; never concatenate with || echo.
    if [[ "$curl_rc" -ne 0 || -z "$code" || "$code" =~ ^0+$ ]]; then
      code="000"
    fi
    # Truncate body artifact if huge HTML 502 page.
    if [[ -f "$out" ]] && [[ "$(wc -c <"$out")" -gt 8192 ]]; then
      head -c 4096 "$out" >"$out.tmp"
      echo "…(truncated)" >>"$out.tmp"
      mv "$out.tmp" "$out"
    fi
    jq -nc --arg n "$name" --arg m "$method" --arg p "$path" --arg c "$code" \
      --argjson s "$elapsed" --argjson rc "$curl_rc" --argjson a "$attempt" \
      '{name:$n,method:$m,path:$p,http_code:$c,elapsed_s:$s,curl_rc:$rc,attempt:$a}' >>"$PROBES_FILE"
    echo "probe $name $method $path → HTTP $code (${elapsed}s curl_rc=$curl_rc attempt=$attempt)" | tee -a "$LOG"

    if [[ "$code" == "502" || "$code" == "503" || "$code" == "504" || "$code" == "000" ]]; then
      if [[ "$attempt" -lt "$max_attempts" ]]; then
        echo "WARN: $name HTTP $code — settle ${settle}s then one retry (nginx Bad Gateway under DataFusion pressure)" \
          | tee -a "$LOG"
        sleep "$settle"
        continue
      fi
      local health_after="dead"
      if health_ok; then health_after="ok"; else health_after="FAIL"; fi
      jq -n \
        --arg n "$name" --arg p "$path" --arg c "$code" --arg h "$health_after" \
        --argjson s "$elapsed" \
        '{ok:false,broke_at:$n,path:$p,http_code:$c,elapsed_s:$s,health_after:$h,building:"'"$BUILDING"'",retried:true}' \
        >"$SUMMARY"
      echo "FAIL: broke at $name HTTP $code health_after=$health_after (after retry)" | tee -a "$LOG"
      exit 1
    fi
    break
  done
  if ! health_ok; then
    jq -n --arg n "$name" --arg c "$code" \
      '{ok:false,broke_at:$n,http_code:$c,health_after:"FAIL",note:"health died after probe"}' \
      >"$SUMMARY"
    echo "FAIL: /api/health not ok after $name (HTTP $code)" | tee -a "$LOG"
    exit 1
  fi
}

BID_JSON="$(jq -nc --arg b "$BUILDING" --arg s "$START_ISO" \
  '{building_id:$b, max_points:4000, start:$s}')"
INSPECT_JSON="$(jq -nc --arg b "$BUILDING" --arg e "$AHU_ID" --arg s "$START_ISO" \
  '{building_id:$b, equipment_ids: (if $e=="" then [] else [$e] end), max_points:500, start:$s}')"

# Order mirrors Overview load + health matrices + a chart-ish inspect.
probe "package_buildings" GET "/api/csv/import/package/buildings"
probe "package_mapping" GET "/api/csv/import/package/mapping?building_id=${BUILDING}"
probe "fdd_equipment" GET "/api/fdd/equipment?building_id=${BUILDING}"
probe "analytics_runtime" POST "/api/analytics/runtime" "$BID_JSON"
probe "analytics_ahu_health" POST "/api/analytics/ahu-health" "$BID_JSON"
probe "analytics_vav_health" POST "/api/analytics/vav-health" "$BID_JSON"
probe "analytics_sensor_faults" POST "/api/analytics/sensor-faults" "$BID_JSON"
probe "analytics_mechanical_cooling" POST "/api/analytics/mechanical-cooling" "$BID_JSON"
probe "analytics_economizer" POST "/api/analytics/economizer" "$BID_JSON"
probe "analytics_bas_vs_web_oat" POST "/api/analytics/bas-vs-web-oat" "$BID_JSON"
probe "analytics_rcx_ahu" POST "/api/analytics/rcx/ahu" "$BID_JSON"
probe "analytics_rcx_presets" GET "/api/analytics/rcx/presets"
if [[ -n "$AHU_ID" ]]; then
  probe "analytics_inspect" POST "/api/analytics/inspect" "$INSPECT_JSON"
fi

jq -n --arg b "$BUILDING" --argjson n "$EQ_N" \
  '{ok:true,building_id:$b,equipment_n:$n,note:"see 37_probes.jsonl"}' >"$SUMMARY"

python3 - "$PROBES_FILE" "$SUMMARY" "$BUILDING" "$EQ_N" <<'PY'
import json,sys
from pathlib import Path
probes=[]
for line in Path(sys.argv[1]).read_text().splitlines():
    line=line.strip()
    if line: probes.append(json.loads(line))
out={
  "ok": True,
  "building_id": sys.argv[3],
  "equipment_n": int(sys.argv[4]),
  "probes": probes,
  "max_elapsed_s": max((p.get("elapsed_s") or 0) for p in probes) if probes else 0,
}
Path(sys.argv[2]).write_text(json.dumps(out, indent=2)+"\n")
print(f"PASS: ACME analytics charts sequential n={len(probes)} max_elapsed_s={out['max_elapsed_s']}")
PY

exit 0
