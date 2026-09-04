#!/usr/bin/env bash
# Creekside-style nested openfdd_package_v1 import spot-check (#805 / 3.3.21).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BASE="${BASE:-http://127.0.0.1:8080}"
FIXTURE_ZIP="${CREEKSIDE_FIXTURE_ZIP:-$ROOT/tests/fixtures/creekside_nested/creekside_nested.zip}"
BENCH_ZIP="${CREEKSIDE_BENCH_ZIP:-/home/ben/OpenFdd_Creekside.zip}"

UTC="$(date -u +%Y%m%dT%H%M%SZ)"
ART="${ARTIFACT_DIR:-$ROOT/reports/creekside-package-import_${UTC}}"
mkdir -p "$ART"

_railway_pw="${RAILWAY_ADMIN_PASSWORD:-}"
if [[ -f "$ROOT/.env" ]]; then
  # shellcheck disable=SC1091
  set -a && source "$ROOT/.env" && set +a
fi
if [[ "${RAILWAY_ONLY:-0}" == "1" && -n "$_railway_pw" ]]; then
  export RAILWAY_ADMIN_PASSWORD="$_railway_pw"
  export OPENFDD_ADMIN_PASSWORD="$_railway_pw"
fi

PASS="${OPENFDD_ADMIN_PASSWORD:-}"
[[ -n "$PASS" ]] || { echo "ERROR: OPENFDD_ADMIN_PASSWORD required" >&2; exit 2; }

login() {
  curl -fsS --max-time 30 -X POST "$BASE/api/auth/login" \
    -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg u admin --arg p "$PASS" '{username:$u,password:$p}')" \
    | jq -r '.token // .access_token // empty'
}

build_fixture_zip() {
  local out="$1"
  local tmp
  tmp="$(mktemp -d)"
  mkdir -p "$tmp/OpenFdd_Creekside/LAKESIDE_ES_openfdd_package_v1/LAKESIDE_ES/AHU_1"
  cat >"$tmp/OpenFdd_Creekside/LAKESIDE_ES_openfdd_package_v1/LAKESIDE_ES/manifest.json" <<'EOF'
{"schema_version":"openfdd_package_v1","building_id":"LAKESIDE_ES","grid_minutes":5,"timezone":"UTC"}
EOF
  cat >"$tmp/OpenFdd_Creekside/LAKESIDE_ES_openfdd_package_v1/LAKESIDE_ES/AHU_1/history_wide.json" <<'EOF'
{"equipType":"ahu","points":{"fan-cmd":"SF_SPD","duct-static-pressure":"DA_P","duct-static-pressure-sp":"DA_P_SP"}}
EOF
  cat >"$tmp/OpenFdd_Creekside/LAKESIDE_ES_openfdd_package_v1/LAKESIDE_ES/AHU_1/history_wide.csv" <<'EOF'
timestamp_utc,SF_SPD,DA_P,DA_P_SP
2024-01-01T00:00:00Z,1,0.5,0.6
2024-01-01T00:05:00Z,1,0.5,0.6
EOF
  echo 'account,billing_period,kwh,demand_kw' >"$tmp/OpenFdd_Creekside/utility_bills_monthly.csv"
  echo 'ACCT1,2024-01,1000,50' >>"$tmp/OpenFdd_Creekside/utility_bills_monthly.csv"
  (cd "$tmp" && zip -qr "$out" OpenFdd_Creekside)
  rm -rf "$tmp"
}

ZIP="$FIXTURE_ZIP"
if [[ ! -f "$ZIP" ]]; then
  mkdir -p "$(dirname "$ZIP")"
  build_fixture_zip "$ZIP"
fi

TOKEN="$(login)"
[[ -n "$TOKEN" ]] || { echo "ERROR: login failed against $BASE" >&2; exit 2; }

import_zip() {
  local label="$1" zip_path="$2"
  local resp="$ART/import_${label}.json"
  curl -fsS --max-time 600 -X POST "$BASE/api/csv/import/package" \
    -H "Authorization: Bearer $TOKEN" \
    -H 'Content-Type: application/zip' \
    --data-binary @"$zip_path" \
    >"$resp" 2>"$ART/import_${label}.err" || echo '{"ok":false}' >"$resp"
  jq -e '.ok == true' "$resp" >/dev/null || {
    echo "FAIL $label import: $(cat "$resp")" >&2
    return 1
  }
  local bid
  bid="$(jq -r '.building_id // empty' "$resp")"
  [[ "$bid" == "LAKESIDE_ES" ]] || {
    echo "FAIL $label building_id=$bid expected LAKESIDE_ES" >&2
    return 1
  }
  echo "OK $label import building_id=$bid"
}

echo "== creekside nested package import =="
echo "artifact=$ART"
import_zip fixture "$ZIP"

if [[ -f "$BENCH_ZIP" && "${RUN_CREEKSIDE_FULL:-0}" == "1" ]]; then
  import_zip full "$BENCH_ZIP"
  # HP matrix / plot smoke — LAKESIDE_ES maps HEAT_PUMP ids (no fake fan_cmd).
  curl -fsS --max-time 120 -X POST "$BASE/api/analytics/hp-health" \
    -H "Authorization: Bearer $TOKEN" \
    -H 'Content-Type: application/json' \
    -d '{"building_id":"LAKESIDE_ES"}' \
    >"$ART/hp_health.json" 2>"$ART/hp_health.err" || echo '{"ok":false}' >"$ART/hp_health.json"
  jq -e '.ok == true' "$ART/hp_health.json" >/dev/null || {
    echo "FAIL hp-health envelope: $(head -c 400 "$ART/hp_health.json")" >&2
    exit 1
  }
  rows="$(jq -r '.analytics.rows // .rows // [] | length' "$ART/hp_health.json")"
  [[ "$rows" -gt 0 ]] || {
    echo "FAIL hp-health expected HP rows for LAKESIDE_ES, got $rows" >&2
    exit 1
  }
  echo "OK hp-health rows=$rows"
  # Spot one HP equipment series path (roles may be sparse without fan_cmd — ok must be true or missing_roles honest).
  HP_EQ="$(jq -r '.analytics.rows // .rows // [] | map(.equipment_id) | .[0] // empty' "$ART/hp_health.json")"
  if [[ -n "$HP_EQ" ]]; then
    curl -fsS --max-time 120 \
      -H "Authorization: Bearer $TOKEN" \
      "$BASE/api/fdd/series?building_id=LAKESIDE_ES&equipment_id=${HP_EQ}&rule_id=HP-1" \
      >"$ART/hp1_series.json" 2>"$ART/hp1_series.err" || true
    if [[ -f "$ART/hp1_series.json" ]]; then
      jq -e '(.ok == true) or (.error != null)' "$ART/hp1_series.json" >/dev/null \
        && echo "OK HP-1 series probe equipment=$HP_EQ" \
        || echo "WARN HP-1 series probe inconclusive for $HP_EQ"
    fi
  fi
fi

jq -n --arg art "$ART" '{ok:true,artifact:$art,building_id:"LAKESIDE_ES"}' >"$ART/summary.json"
echo "PASS creekside_package_import_spot"
