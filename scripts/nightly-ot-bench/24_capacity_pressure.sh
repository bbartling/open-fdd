#!/usr/bin/env bash
# Gate 24 — Railway capacity pressure probe (Wave S S5a).
# Building-scoped FDD/analytics burst; hard-fail on 5xx/timeout/health death.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib.sh"
# shellcheck disable=SC1091
source "$DIR/lib_capacity_sample.sh"
load_bench_env
cd "$ROOT"

ART="${ARTIFACT_DIR:-$(artifact_dir)}"
mkdir -p "$ART"
export ARTIFACT_DIR="$ART"
export OPENFDD_STRESS_GATE="24_capacity_pressure"
LOG="$ART/24_capacity_pressure.log"
: >"$LOG"

if [[ "${RAILWAY_ONLY:-0}" != "1" && "${CAPACITY_PRESSURE:-0}" != "1" ]]; then
  echo "SKIP: set RAILWAY_ONLY=1 or CAPACITY_PRESSURE=1" | tee -a "$LOG"
  exit 0
fi

BASE="${OPENFDD_API_BASE:-${CENTRAL_BASE:-}}"
TOK="${OPENFDD_ADMIN_TOKEN:-}"
if [[ -z "$TOK" ]]; then
  # Prefer hub password already in env (Railway stress mints token up-front).
  if [[ -n "${OPENFDD_ADMIN_PASSWORD:-}" ]]; then
    TOK="$(
      curl -sf --max-time 30 -X POST "$BASE/api/auth/login" \
        -H 'Content-Type: application/json' \
        -d "$(jq -nc --arg p "$OPENFDD_ADMIN_PASSWORD" '{username:"admin",password:$p}')" \
        | jq -r '.token // .access_token // empty'
    )"
  fi
fi
if [[ -z "$TOK" ]]; then
  echo "ERROR: OPENFDD_ADMIN_TOKEN required (or OPENFDD_ADMIN_PASSWORD for login)" | tee -a "$LOG"
  exit 1
fi
export OPENFDD_ADMIN_TOKEN="$TOK"
capacity_sample_once || true

BUILDINGS_JSON="$ART/24_buildings.json"
code="$(http_code_to "$BUILDINGS_JSON" --max-time 30 \
  -H "Authorization: Bearer $TOK" "$BASE/api/csv/import/package/buildings")"
echo "buildings HTTP $code" | tee -a "$LOG"

PICK="$(python3 - "$BUILDINGS_JSON" <<'PY'
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
buildings = []
if p.is_file():
    try:
        body = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        body = {}
    for b in body.get("buildings") or []:
        if isinstance(b, str) and b.strip():
            buildings.append(b.strip())
        elif isinstance(b, dict):
            bid = b.get("building_id") or b.get("id") or ""
            if bid:
                buildings.append(str(bid))
prefer = ["ACME", "BUILDING_100", "LAKESIDE_ES", "CREEKSIDE"]
for pref in prefer:
    for b in buildings:
        if b.upper() == pref or pref in b.upper():
            print(b)
            raise SystemExit
print(buildings[0] if buildings else "")
PY
)"

if [[ -z "$PICK" ]]; then
  EDGES="$ART/24_edges.json"
  http_code_to "$EDGES" --max-time 20 -H "Authorization: Bearer $TOK" "$BASE/api/edges" >/dev/null || true
  PICK="$(jq -r '.edges[0].site_id // empty' "$EDGES" 2>/dev/null || true)"
fi

if [[ -z "$PICK" ]]; then
  echo "FAIL: no building_id available for capacity pressure" | tee -a "$LOG"
  exit 1
fi
echo "pressure building_id=$PICK" | tee -a "$LOG"

BUDGET="${CAPACITY_FDD_P95_SECS:-180}"
EQ_URL="$(python3 -c "import urllib.parse,sys; print(sys.argv[1].rstrip('/') + '/api/fdd/equipment?building_id=' + urllib.parse.quote(sys.argv[2]))" "$BASE" "$PICK")"
EQ_BODY="$ART/24_equipment.json"
eq_code="$(http_code_to "$EQ_BODY" --max-time 60 \
  -H "Authorization: Bearer $TOK" "$EQ_URL")"
echo "equipment HTTP $eq_code" | tee -a "$LOG"

if [[ "$eq_code" == "502" || "$eq_code" == "503" || "$eq_code" == "504" || "$eq_code" == "000" ]]; then
  echo "FAIL: equipment list HTTP $eq_code under pressure" | tee -a "$LOG"
  exit 1
fi

EQ_ID="$(python3 - "$EQ_BODY" <<'PY'
import json, sys
from pathlib import Path
body = {}
try:
    body = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except Exception:
    pass

def score(eid: str) -> int:
    u = eid.upper()
    if "WEATHER" in u or u.endswith("_OA") or u == "OA":
        return 0
    if any(x in u for x in ("AHU", "RTU", "VAV", "CHILL", "BOIL", "FCU", "HP")):
        return 3
    return 2

cands: list[str] = []
for key in ("equipment_ids", "equipment", "items", "rows"):
    arr = body.get(key)
    if not isinstance(arr, list):
        continue
    for first in arr:
        if isinstance(first, str) and first.strip():
            cands.append(first.strip())
        elif isinstance(first, dict):
            for k in ("equipment_id", "id", "name"):
                if first.get(k):
                    cands.append(str(first[k]))
                    break
if not cands:
    print("")
else:
    cands.sort(key=score, reverse=True)
    print(cands[0])
PY
)"

FDD_BODY="$ART/24_fdd_run.json"
START_S="$(date +%s)"
ANALYTICS_CODE="000"
if [[ -n "$EQ_ID" ]]; then
  echo "equipment_id=$EQ_ID" | tee -a "$LOG"
  PAYLOAD="$(jq -nc --arg b "$PICK" --arg e "$EQ_ID" \
    '{building_id:$b, equipment_id:$e, rule_ids:["FC1"], confirm:true}')"
  ANALYTICS_CODE="$(http_code_to "$FDD_BODY" --max-time "$BUDGET" \
    -X POST -H "Authorization: Bearer $TOK" -H 'Content-Type: application/json' \
    -d "$PAYLOAD" "$BASE/api/fdd/run")"
  echo "fdd/run HTTP $ANALYTICS_CODE" | tee -a "$LOG"
else
  PAYLOAD="$(jq -nc --arg b "$PICK" '{building_id:$b}')"
  ANALYTICS_CODE="$(http_code_to "$FDD_BODY" --max-time "$BUDGET" \
    -X POST -H "Authorization: Bearer $TOK" -H 'Content-Type: application/json' \
    -d "$PAYLOAD" "$BASE/api/analytics/runtime")"
  echo "analytics/runtime HTTP $ANALYTICS_CODE (no equipment)" | tee -a "$LOG"
fi
END_S="$(date +%s)"
ELAPSED_S=$((END_S - START_S))
echo "elapsed_s=$ELAPSED_S budget_s=$BUDGET" | tee -a "$LOG"

if [[ "$ANALYTICS_CODE" == "502" || "$ANALYTICS_CODE" == "503" || "$ANALYTICS_CODE" == "504" || "$ANALYTICS_CODE" == "000" ]]; then
  echo "FAIL: query path HTTP $ANALYTICS_CODE" | tee -a "$LOG"
  exit 1
fi

SOFT=0
if (( ELAPSED_S > BUDGET )); then
  echo "SOFT_WARN: elapsed_s=$ELAPSED_S exceeds CAPACITY_FDD_P95_SECS=$BUDGET" | tee -a "$LOG"
  SOFT=1
fi

HEALTH="$(curl -sf --max-time 20 "$BASE/api/health" || echo '{}')"
echo "$HEALTH" >"$ART/24_health_after.json"
if ! echo "$HEALTH" | jq -e '.ok == true' >/dev/null 2>&1; then
  echo "FAIL: health not ok after pressure" | tee -a "$LOG"
  exit 1
fi

capacity_sample_once || true

jq -n \
  --arg b "$PICK" \
  --arg eq "${EQ_ID:-}" \
  --arg code "$ANALYTICS_CODE" \
  --argjson secs "$ELAPSED_S" \
  --argjson soft "$SOFT" \
  '{ok:true, building_id:$b, equipment_id:$eq, http_code:$code, elapsed_s:$secs, soft_latency_warn:($soft==1)}' \
  >"$ART/24_capacity_pressure_summary.json"

if [[ "$SOFT" == "1" && "${CAPACITY_STRICT:-0}" == "1" ]]; then
  echo "FAIL: CAPACITY_STRICT latency soft warn" | tee -a "$LOG"
  exit 1
fi

echo "PASS: capacity pressure building=$PICK http=$ANALYTICS_CODE" | tee -a "$LOG"
exit 0
