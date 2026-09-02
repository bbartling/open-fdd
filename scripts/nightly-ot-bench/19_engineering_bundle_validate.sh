#!/usr/bin/env bash
# Gate 19 — Engineering & ML bundle structural validate (#763).
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib.sh"
load_bench_env
cd "$ROOT"

ART="${ARTIFACT_DIR:-$(artifact_dir)}"
mkdir -p "$ART"

hdr "Engineering bundle validate (gate 19)"

BASE="${BASE:-http://127.0.0.1:8080}"
BUILDING_ID="${BUILDING_ID:-BUILDING_100}"
ADMIN_PASS="${OPENFDD_ADMIN_PASSWORD:-}"

login() {
  curl -fsS --max-time 30 -X POST "$BASE/api/auth/login" \
    -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg u admin --arg p "$ADMIN_PASS" '{username:$u,password:$p}')" \
    | jq -r '.token // .access_token // empty'
}

if [[ -z "$ADMIN_PASS" ]]; then
  bad "OPENFDD_ADMIN_PASSWORD required"
fi

TOKEN="$(login)"
[[ -n "$TOKEN" ]] || bad "login failed"

JOB_JSON="$ART/job_create.json"
curl -fsS --max-time 60 -X POST "$BASE/api/jobs" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg b "$BUILDING_ID" '{job_name:"gate19 bundle",site_id:$b}')" \
  >"$JOB_JSON" 2>"$ART/job_create.err" || bad "job create failed"
JOB_ID="$(jq -r '.job.job_id // .job_id // empty' "$JOB_JSON")"
[[ -n "$JOB_ID" ]] || bad "missing job_id"

EXPORT_JSON="$ART/export_create.json"
curl -fsS --max-time 300 -X POST "$BASE/api/jobs/$JOB_ID/exports" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg b "$BUILDING_ID" '{building_id:$b,profile:"summary"}')" \
  >"$EXPORT_JSON" 2>"$ART/export_create.err" || bad "export create failed"
EXPORT_ID="$(jq -r '.export.export_id // empty' "$EXPORT_JSON")"
[[ -n "$EXPORT_ID" ]] || bad "missing export_id"

ZIP_PATH="$ART/engineering_bundle.zip"
curl -fsS --max-time 300 \
  -H "Authorization: Bearer $TOKEN" \
  "$BASE/api/jobs/$JOB_ID/exports/$EXPORT_ID/download" \
  -o "$ZIP_PATH" 2>"$ART/download.err" || bad "export download failed"
[[ -s "$ZIP_PATH" ]] || bad "empty bundle zip"

VALIDATE_JSON="$ART/bundle_validate.json"
python3 "$ROOT/scripts/openfdd_bundle_validate.py" validate "$ZIP_PATH" >"$VALIDATE_JSON"
STATUS="$(jq -r '.status // "NOT_READY"' "$VALIDATE_JSON")"
if [[ "$STATUS" == "NOT_READY" ]]; then
  jq . "$VALIDATE_JSON" >&2
  bad "bundle validator NOT_READY"
fi

ok "engineering bundle $STATUS ($ZIP_PATH)"
echo "$VALIDATE_JSON"
