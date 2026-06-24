#!/usr/bin/env bash
# CSV import sidecar — orchestrates Open-FDD import API (no direct Feather writes).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

ENABLED="${OPENFDD_IMPORT_SIDECAR_ENABLED:-1}"
INPUT_DIR="${OPENFDD_IMPORT_SIDECAR_INPUT_DIR:-$ROOT/workspace/imports/incoming}"
PROCESSING_DIR="${OPENFDD_IMPORT_SIDECAR_PROCESSING_DIR:-$ROOT/workspace/imports/processing}"
ARCHIVE_DIR="${OPENFDD_IMPORT_SIDECAR_ARCHIVE_DIR:-$ROOT/workspace/imports/archive}"
FAILED_DIR="${OPENFDD_IMPORT_SIDECAR_FAILED_DIR:-$ROOT/workspace/imports/failed}"
REPORT_DIR="${OPENFDD_IMPORT_SIDECAR_REPORT_DIR:-$ROOT/workspace/imports/reports}"
API_BASE="${OPENFDD_IMPORT_SIDECAR_API_BASE:-http://127.0.0.1:8080}"
PROFILE="${OPENFDD_IMPORT_SIDECAR_PROFILE:-default_csv_import}"
MAX_FILES="${OPENFDD_IMPORT_SIDECAR_MAX_FILES:-25}"
MAX_FILE_MB="${OPENFDD_IMPORT_SIDECAR_MAX_FILE_MB:-250}"
DELETE_AFTER="${OPENFDD_IMPORT_SIDECAR_DELETE_AFTER_SUCCESS:-0}"
DRY_RUN="${OPENFDD_IMPORT_SIDECAR_DRY_RUN:-0}"
GLOB="${OPENFDD_IMPORT_SIDECAR_GLOB:-*.csv}"
LOCKFILE="${OPENFDD_IMPORT_SIDECAR_LOCKFILE:-/tmp/openfdd_csv_import_sidecar.lock}"
TOKEN_FILE="${OPENFDD_IMPORT_SIDECAR_AUTH_TOKEN_FILE:-}"
AUTH_ENV="${OPENFDD_IMPORT_SIDECAR_AUTH_ENV:-$ROOT/workspace/auth.env.local}"

[[ "$ENABLED" == "1" ]] || exit 0
mkdir -p "$INPUT_DIR" "$PROCESSING_DIR" "$ARCHIVE_DIR" "$FAILED_DIR" "$REPORT_DIR"

exec 9>"$LOCKFILE"
if ! flock -n 9; then
  echo "import sidecar already running (lock=$LOCKFILE)" >&2
  exit 0
fi

redact_auth() {
  sed -E 's/(Authorization:[[:space:]]*Bearer)[[:space:]]+[^[:space:]]+/\1 ***REDACTED***/Ig'
}

safe_name() {
  local base
  base="$(basename "$1")"
  [[ "$base" == *".."* || "$base" == /* ]] && return 1
  [[ "$base" == *.csv ]] || return 1
  printf '%s' "$base"
}

auth_header() {
  if [[ -n "$TOKEN_FILE" && -f "$TOKEN_FILE" ]]; then
    printf 'Authorization: Bearer %s' "$(tr -d '\r\n' <"$TOKEN_FILE")"
    return
  fi
  if [[ ! -f "$AUTH_ENV" ]]; then
    echo "ERROR: set OPENFDD_IMPORT_SIDECAR_AUTH_TOKEN_FILE or provide $AUTH_ENV" >&2
    exit 1
  fi
  local user="${OPENFDD_IMPORT_SIDECAR_USER:-integrator}"
  local pw
  pw="$(grep '^OFDD_INTEGRATOR_PASSWORD=' "$AUTH_ENV" | cut -d= -f2- | tr -d '\r')"
  [[ "$user" == "agent" ]] && pw="$(grep '^OFDD_AGENT_PASSWORD=' "$AUTH_ENV" | cut -d= -f2- | tr -d '\r')"
  local token
  token="$(curl -fsS -X POST "$API_BASE/api/auth/login" \
    -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg u "$user" --arg p "$pw" '{username:$u,password:$p}')" \
    | jq -r '.token // .access_token')"
  printf 'Authorization: Bearer %s' "$token"
}

AUTH="$(auth_header)"
shopt -s nullglob
mapfile -t files < <(find "$INPUT_DIR" -maxdepth 1 -type f -name "$GLOB" | sort | head -n "$MAX_FILES")
processed=0
failed=0

for src in "${files[@]}"; do
  name="$(safe_name "$src")" || { echo "reject unsafe path $src" | redact_auth; continue; }
  [[ -L "$src" ]] && { echo "reject symlink $src"; continue; }
  size_mb=$(( $(stat -c%s "$src") / 1024 / 1024 ))
  if [[ "$size_mb" -gt "$MAX_FILE_MB" ]]; then
    echo "reject oversize $name (${size_mb}MB)" >&2
    mv "$src" "$FAILED_DIR/" || true
    failed=$((failed + 1))
    continue
  fi
  work="$PROCESSING_DIR/$name"
  mv "$src" "$work"
  report="$REPORT_DIR/${name%.csv}_$(date -u +%Y%m%dT%H%M%SZ).json"
  if [[ "$DRY_RUN" == "1" ]]; then
    jq -nc --arg f "$name" --arg p "$PROFILE" '{ok:true,dry_run:true,file:$f,profile:$p}' >"$report"
    mv "$work" "$ARCHIVE_DIR/" || true
    processed=$((processed + 1))
    continue
  fi
  job="$(curl -fsS -X POST "$API_BASE/api/import/jobs" \
    -H "$AUTH" -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg p "$PROFILE" '{profile_id:$p,source_id:"source:csv-import-sidecar"}')" )"
  job_id="$(echo "$job" | jq -r '.job_id // empty')"
  if [[ -z "$job_id" ]]; then
    echo "$job" | redact_auth >"$report"
    mv "$work" "$FAILED_DIR/" || true
    failed=$((failed + 1))
    continue
  fi
  curl -fsS -X POST "$API_BASE/api/import/jobs/$job_id/upload" \
    -H "$AUTH" -H 'Content-Type: text/csv' --data-binary @"$work" >/dev/null
  curl -fsS "$API_BASE/api/import/jobs/$job_id/preview" -H "$AUTH" >/dev/null
  result="$(curl -fsS -X POST "$API_BASE/api/import/jobs/$job_id/commit" -H "$AUTH")"
  echo "$result" >"$report"
  if jq -e '.ok == true and .status == "completed"' "$report" >/dev/null; then
    if [[ "$DELETE_AFTER" == "1" ]]; then rm -f "$work"; else mv "$work" "$ARCHIVE_DIR/"; fi
    processed=$((processed + 1))
  else
    mv "$work" "$FAILED_DIR/" || true
    failed=$((failed + 1))
  fi
done

echo "import sidecar done processed=$processed failed=$failed"
[[ "$failed" -eq 0 ]]
