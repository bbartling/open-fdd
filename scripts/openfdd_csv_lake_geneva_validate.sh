#!/usr/bin/env bash
# Validate Lake Geneva 5-file CSV fusion: upload → join plan → fusion preview → save.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_auth_lib.sh
source "$ROOT/scripts/openfdd_auth_lib.sh"

FIXTURE_DIR="${OPENFDD_CSV_FIXTURE_DIR:-/mnt/c/Users/ben/OneDrive/Desktop/testing/lake_geneva}"
API="${OPENFDD_API_BASE:-http://127.0.0.1:8080}"
AUTH="$ROOT/workspace/auth.env.local"

SCHOOL=(
  "School_2013_2014_KW.csv"
  "School_2014_2015 KW.csv"
  "School_2015_2016 KW.csv"
  "School_2016_2017_KW.csv"
)
WEATHER="lake_geneva_wi_open_meteo_2013_2018_hourly.csv"

for f in "${SCHOOL[@]}" "$WEATHER"; do
  test -f "$FIXTURE_DIR/$f" || {
    echo "ERROR: missing fixture $FIXTURE_DIR/$f" >&2
    echo "Set OPENFDD_CSV_FIXTURE_DIR to folder with Lake Geneva CSVs." >&2
    exit 1
  }
done

TOKEN="$(openfdd_auth_login_token "$API" "$AUTH" integrator)" || exit 1

echo "== Upload 5 CSVs (multipart) =="
UPLOAD_ARGS=()
for f in "${SCHOOL[@]}" "$WEATHER"; do
  UPLOAD_ARGS+=(-F "file=@${FIXTURE_DIR}/${f}")
done
PREV="$(curl -fsS -X POST "$API/api/csv/import/preview" \
  -H "Authorization: Bearer $TOKEN" \
  "${UPLOAD_ARGS[@]}")"
SID="$(echo "$PREV" | jq -r '.session_id // empty')"
FCOUNT="$(echo "$PREV" | jq '.files | length')"
echo "session=$SID files=$FCOUNT ok=$(echo "$PREV" | jq -r '.ok')"
test "$FCOUNT" -eq 5 || {
  echo "$PREV" | jq '.errors // .'
  exit 1
}

WX_HEADERS="$(echo "$PREV" | jq -r --arg w "$WEATHER" '.files[] | select(.filename==$w) | .profile.headers | @json')"
WX_VALS="$(echo "$WX_HEADERS" | jq -c 'map(select(. != "time_local" and . != "timezone" and . != "Date"))[:12]')"

PLAN_FILES="$(jq -nc \
  --argjson schools "$(printf '%s\n' "${SCHOOL[@]}" | jq -R . | jq -s 'map({filename:., timestamp_column:"Date", timezone:"America/Chicago", value_columns:["kW"]})')" \
  --arg wx "$WEATHER" \
  --argjson wx_vals "$WX_VALS" \
  '$schools + [{filename:$wx, timestamp_column:"time_local", timezone:"America/Chicago", value_columns:$wx_vals}]')"

echo "== Plan (join: append schools + floor_hour weather) =="
PLAN="$(curl -fsS -X POST "$API/api/csv/import/plan" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "$(jq -nc --arg sid "$SID" --argjson files "$PLAN_FILES" \
    '{session_id:$sid, plan:{mode:"join", output_dataset_name:"lake_geneva_school_merged", ambiguous_policy:"first", fill_policy:"forward", join_alignment:"floor_hour", files:$files}}')")"
ROWS="$(echo "$PLAN" | jq -r '.preview.row_count // 0')"
DUP="$(echo "$PLAN" | jq -r '.preview.timestamp_analysis.duplicate_local_count // 0')"
AMB="$(echo "$PLAN" | jq -r '.preview.timestamp_analysis.ambiguous_count // 0')"
RANGE="$(echo "$PLAN" | jq -c '.preview.time_range // null')"
echo "rows=$ROWS dup_local=$DUP ambiguous=$AMB range=$RANGE"
test "$ROWS" -gt 100000 || {
  echo "ERROR: expected >100k merged rows, got $ROWS" >&2
  exit 1
}

echo "== Fusion preview =="
FUSION="$(curl -fsS "$API/api/csv/import/sessions/${SID}/fusion-preview?limit=3" \
  -H "Authorization: Bearer $TOKEN")"
echo "fusion rows=$(echo "$FUSION" | jq -r '.row_count') cols=$(echo "$FUSION" | jq -r '.columns | length')"

echo "== Save Arrow dataset =="
SAVE="$(curl -fsS -X POST "$API/api/csv/import/execute" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "$(jq -nc --arg sid "$SID" '{session_id:$sid, confirm:true}')")"
DS_ROWS="$(echo "$SAVE" | jq -r '.dataset.row_count // 0')"
DS_ID="$(echo "$SAVE" | jq -r '.dataset.id // empty')"
echo "dataset=$DS_ID rows=$DS_ROWS"
test "$DS_ROWS" -gt 100000 || exit 1

echo "OK: Lake Geneva 5-file CSV fusion validated (session $SID, dataset $DS_ID)"
