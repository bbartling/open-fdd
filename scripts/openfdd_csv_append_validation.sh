#!/usr/bin/env bash
# CSV append/import/export/purge helpers for live FDD validation (device 5007).
# Sourced from smoke_live_fdd_validation.sh — not executed directly.
set -euo pipefail

openfdd_csv_append_init() {
  local log_dir="$1"
  CSV_APPEND_LOG_DIR="$log_dir"
  CSV_APPEND_SOURCE_ID="${OPENFDD_CSV_SOURCE_ID:-source:validation-csv}"
  CSV_APPEND_EQUIPMENT_ID="${OPENFDD_CSV_EQUIPMENT_ID:-5007}"
  CSV_APPEND_PROFILE="${OPENFDD_CSV_IMPORT_PROFILE:-validation_csv_5007}"
  CSV_APPEND_BATCH="${CSV_APPEND_BATCH:-0}"
  CSV_APPEND_HIST_ROWS_BEFORE=0
  CSV_APPEND_HIST_ROWS_AFTER=0
  CSV_APPEND_JOB_IDS=()
  mkdir -p "$log_dir/csv_batches"
}

openfdd_csv_append_generate() {
  local ts="$1"
  local phase="${2:-normal}"
  local batch="$3"
  local out="$CSV_APPEND_LOG_DIR/csv_batches/batch_${batch}.csv"
  local oa_t=65.0 oa_h=45.0 duct_t=55.0 zn_t=72.0
  if [[ "$phase" == "fault" ]]; then
    oa_t=120.0
    duct_t=95.0
  fi
  cat >"$out" <<EOF
timestamp,equipment_id,point_key,value,units,source_id
${ts},${CSV_APPEND_EQUIPMENT_ID},oa_t,${oa_t},degF,${CSV_APPEND_SOURCE_ID}
${ts},${CSV_APPEND_EQUIPMENT_ID},oa_h,${oa_h},%,${CSV_APPEND_SOURCE_ID}
${ts},${CSV_APPEND_EQUIPMENT_ID},duct_t,${duct_t},degF,${CSV_APPEND_SOURCE_ID}
${ts},${CSV_APPEND_EQUIPMENT_ID},zn_t,${zn_t},degF,${CSV_APPEND_SOURCE_ID}
EOF
  printf '%s' "$out"
}

openfdd_csv_append_import_batch() {
  local base="$1"
  local token="$2"
  local ts="$3"
  local phase="$4"
  local batch="$5"

  CSV_APPEND_BATCH="$batch"
  local csv_path
  csv_path="$(openfdd_csv_append_generate "$ts" "$phase" "$batch")"

  local job_resp job_id
  job_resp="$(curl "${CURL_TLS[@]:-}" -fsS -X POST "${base}/api/import/jobs" \
    -H "Authorization: Bearer $token" \
    -H 'Content-Type: application/json' \
    -d "$(jq -nc \
      --arg profile "$CSV_APPEND_PROFILE" \
      --arg src "$CSV_APPEND_SOURCE_ID" \
      --arg equip "$CSV_APPEND_EQUIPMENT_ID" \
      '{profile_id:$profile,source_id:$src,equipment_id:$equip}')")"
  job_id="$(jq -r '.job_id // empty' <<<"$job_resp")"
  [[ -n "$job_id" ]] || { echo "csv import job create failed: $job_resp" >&2; return 1; }

  curl "${CURL_TLS[@]:-}" -fsS -X POST "${base}/api/import/jobs/${job_id}/upload" \
    -H "Authorization: Bearer $token" \
    -H 'Content-Type: text/csv' \
    --data-binary @"$csv_path" >/dev/null

  curl "${CURL_TLS[@]:-}" -fsS "${base}/api/import/jobs/${job_id}/preview" \
    -H "Authorization: Bearer $token" \
    -o "$CSV_APPEND_LOG_DIR/csv_preview_${batch}.json"

  curl "${CURL_TLS[@]:-}" -fsS -X PATCH "${base}/api/import/jobs/${job_id}/options" \
    -H "Authorization: Bearer $token" \
    -H 'Content-Type: application/json' \
    -d "$(jq -nc \
      --arg src "$CSV_APPEND_SOURCE_ID" \
      --arg equip "$CSV_APPEND_EQUIPMENT_ID" \
      '{source_id:$src,equipment_id:$equip,append:true}')" >/dev/null

  local commit_resp
  commit_resp="$(curl "${CURL_TLS[@]:-}" -fsS -X POST "${base}/api/import/jobs/${job_id}/commit" \
    -H "Authorization: Bearer $token")"
  echo "$commit_resp" >"$CSV_APPEND_LOG_DIR/csv_commit_${batch}.json"
  CSV_APPEND_JOB_IDS+=("$job_id")
}

openfdd_csv_append_hist_rows() {
  local base="$1"
  local token="$2"
  curl "${CURL_TLS[@]:-}" -fsS "${base}/api/historian/validation/status" \
    -H "Authorization: Bearer $token" \
    | jq -r '.row_count // 0'
}

openfdd_csv_append_export_checks() {
  local base="$1"
  local token="$2"
  local tag="$3"
  local out="$CSV_APPEND_LOG_DIR/export_${tag}"
  mkdir -p "$out"
  for path in historian.csv faults.csv model-points.csv validation-runs.csv import-jobs.csv; do
    curl "${CURL_TLS[@]:-}" -fsS "${base}/api/export/${path}" \
      -H "Authorization: Bearer $token" \
      -o "$out/$path" || return 1
    head -1 "$out/$path" >"$out/${path}.header"
  done
  jq -nc \
    --arg tag "$tag" \
    --arg dir "$out" \
    --arg hist "$(wc -l <"$out/historian.csv" | tr -d ' ')" \
    '{tag:$tag,dir:$dir,historian_lines:($hist|tonumber)}' \
    >"$out/manifest.json"
}

openfdd_csv_append_purge_validation() {
  local base="$1"
  local token="$2"
  local started="$3"
  local finished="$4"

  local preview
  preview="$(curl "${CURL_TLS[@]:-}" -fsS -X POST "${base}/api/data-management/purge/preview" \
    -H "Authorization: Bearer $token" \
    -H 'Content-Type: application/json' \
    -d "$(jq -nc \
      --arg src "$CSV_APPEND_SOURCE_ID" \
      --arg equip "$CSV_APPEND_EQUIPMENT_ID" \
      --arg after "$started" \
      --arg before "$finished" \
      '{source_id:$src,equipment_id:$equip,after_utc:$after,before_utc:$before,historian_subdir:"validation",validation_run:true}')")"
  echo "$preview" >"$CSV_APPEND_LOG_DIR/purge_preview.json"
  local matched
  matched="$(jq -r '.matched_row_count // 0' <<<"$preview")"
  [[ "$matched" -gt 0 ]] || echo "WARN: purge preview matched 0 rows" >&2

  curl "${CURL_TLS[@]:-}" -fsS -X POST "${base}/api/data-management/purge/execute" \
    -H "Authorization: Bearer $token" \
    -H 'Content-Type: application/json' \
    -d "$(jq -nc \
      --arg src "$CSV_APPEND_SOURCE_ID" \
      --arg equip "$CSV_APPEND_EQUIPMENT_ID" \
      --arg after "$started" \
      --arg before "$finished" \
      '{source_id:$src,equipment_id:$equip,after_utc:$after,before_utc:$before,historian_subdir:"validation",validation_run:true,confirmation:"PURGE HISTORIAN DATA"}')" \
    >"$CSV_APPEND_LOG_DIR/purge_execute.json"
}
