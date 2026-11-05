#!/usr/bin/env bash
# CSV export sidecar — calls authenticated export APIs (no direct Feather reads).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

ENABLED="${OPENFDD_EXPORT_SIDECAR_ENABLED:-1}"
OUTPUT_DIR="${OPENFDD_EXPORT_SIDECAR_OUTPUT_DIR:-$ROOT/workspace/exports}"
FAILED_DIR="${OPENFDD_EXPORT_SIDECAR_FAILED_DIR:-$ROOT/workspace/exports/failed}"
REPORT_DIR="${OPENFDD_EXPORT_SIDECAR_REPORT_DIR:-$ROOT/workspace/exports/reports}"
API_BASE="${OPENFDD_EXPORT_SIDECAR_API_BASE:-http://127.0.0.1:8080}"
PROFILE="${OPENFDD_EXPORT_SIDECAR_PROFILE:-default_bulk_export}"
RETENTION_DAYS="${OPENFDD_EXPORT_SIDECAR_RETENTION_DAYS:-30}"
DRY_RUN="${OPENFDD_EXPORT_SIDECAR_DRY_RUN:-0}"
LOCKFILE="${OPENFDD_EXPORT_SIDECAR_LOCKFILE:-/tmp/openfdd_csv_export_sidecar.lock}"
TOKEN_FILE="${OPENFDD_EXPORT_SIDECAR_AUTH_TOKEN_FILE:-}"
AUTH_ENV="${OPENFDD_EXPORT_SIDECAR_AUTH_ENV:-$ROOT/workspace/auth.env.local}"
LOOKBACK_HOURS="${OPENFDD_EXPORT_LOOKBACK_HOURS:-24}"

[[ "$ENABLED" == "1" ]] || exit 0
mkdir -p "$OUTPUT_DIR" "$FAILED_DIR" "$REPORT_DIR"

exec 9>"$LOCKFILE"
if ! flock -n 9; then
  echo "export sidecar already running (lock=$LOCKFILE)" >&2
  exit 0
fi

auth_header() {
  if [[ -n "$TOKEN_FILE" && -f "$TOKEN_FILE" ]]; then
    printf 'Authorization: Bearer %s' "$(tr -d '\r\n' <"$TOKEN_FILE")"
    return
  fi
  local user="${OPENFDD_EXPORT_SIDECAR_USER:-operator}"
  local pw
  pw="$(grep '^OFDD_OPERATOR_PASSWORD=' "$AUTH_ENV" | cut -d= -f2- | tr -d '\r')"
  [[ "$user" == "integrator" ]] && pw="$(grep '^OFDD_INTEGRATOR_PASSWORD=' "$AUTH_ENV" | cut -d= -f2- | tr -d '\r')"
  local token
  token="$(curl -fsS -X POST "$API_BASE/api/auth/login" \
    -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg u "$user" --arg p "$pw" '{username:$u,password:$p}')" \
    | jq -r '.token // .access_token')"
  printf 'Authorization: Bearer %s' "$token"
}

safe_out_name() {
  local name="$1"
  [[ "$name" == *".."* || "$name" == /* || "$name" == *"/"* ]] && return 1
  printf '%s' "$name"
}

fetch_export() {
  local path="$1" out_name="$2"
  out_name="$(safe_out_name "$out_name")" || return 1
  local tmp="$OUTPUT_DIR/.tmp_${out_name}.$$"
  local final="$OUTPUT_DIR/$out_name"
  if [[ "$DRY_RUN" == "1" ]]; then
    jq -nc --arg p "$path" --arg o "$out_name" '{ok:true,dry_run:true,path:$p,output:$o}' \
      >"$REPORT_DIR/${out_name%.csv}_$(date -u +%Y%m%dT%H%M%SZ).json"
    return 0
  fi
  if ! curl -fsS "$API_BASE$path" -H "$AUTH" -o "$tmp"; then
    return 1
  fi
  head -1 "$tmp" | grep -q ',' || { rm -f "$tmp"; return 1; }
  mv -f "$tmp" "$final"
  jq -nc --arg p "$path" --arg o "$final" --argjson bytes "$(wc -c <"$final")" \
    '{ok:true,path:$p,output:$o,bytes:$bytes}' \
    >"$REPORT_DIR/${out_name%.csv}_$(date -u +%Y%m%dT%H%M%SZ).json"
}

AUTH="$(auth_header)"
DATE_TAG="$(date -u +%Y%m%d)"
failures=0

exports=(
  "/api/export/historian.csv?hours=$LOOKBACK_HOURS|openfdd_historian_${DATE_TAG}.csv"
  "/api/export/faults.csv?hours=$LOOKBACK_HOURS|openfdd_faults_${DATE_TAG}.csv"
  "/api/export/fault-summary.csv?hours=$LOOKBACK_HOURS|openfdd_fault_summary_${DATE_TAG}.csv"
  "/api/export/model-points.csv|openfdd_model_points_${DATE_TAG}.csv"
  "/api/bacnet/overrides/export|openfdd_bacnet_overrides_${DATE_TAG}.csv"
  "/api/export/validation-runs.csv|openfdd_validation_runs_${DATE_TAG}.csv"
  "/api/export/import-jobs.csv|openfdd_import_jobs_${DATE_TAG}.csv"
)

for item in "${exports[@]}"; do
  path="${item%%|*}"
  file="${item##*|}"
  fetch_export "$path" "$file" || failures=$((failures + 1))
done

find "$OUTPUT_DIR" -maxdepth 1 -type f -name 'openfdd_*.csv' -mtime +"$RETENTION_DAYS" -delete 2>/dev/null || true

echo "export sidecar profile=$PROFILE failures=$failures output=$OUTPUT_DIR"
[[ "$failures" -eq 0 ]]
