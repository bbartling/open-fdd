#!/usr/bin/env bash
# Gate 19 — Engineering & ML bundle structural validate (#763 / #1149).
# Ensures the target building has an imported package (seed on miss) before
# POST /api/jobs/{id}/exports, and surfaces package_missing JSON on hard fail.
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
SEED_DIR="$DIR/fixtures/gate19_seed"
PACKAGE_ZIP="${GATE19_PACKAGE_ZIP:-}"

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

auth=(-H "Authorization: Bearer $TOKEN")

list_buildings() {
  curl -fsS --max-time 60 "${auth[@]}" \
    "$BASE/api/csv/import/package/buildings" \
    | tee "$ART/package_buildings.json"
}

building_present() {
  local bid="$1"
  jq -e --arg b "$bid" '
    ((.buildings // []) | map(tostring) | index($b)) != null
  ' "$ART/package_buildings.json" >/dev/null 2>&1
}

build_seed_zip() {
  local out="$1"
  python3 - "$SEED_DIR" "$out" <<'PY'
import pathlib, sys, zipfile
seed = pathlib.Path(sys.argv[1])
out = pathlib.Path(sys.argv[2])
if not (seed / "BUILDING_100" / "manifest.json").is_file():
    raise SystemExit(f"missing seed fixture under {seed}")
with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
    for path in sorted(seed.rglob("*")):
        if path.is_file():
            zf.write(path, path.relative_to(seed).as_posix())
print(out)
PY
}

ensure_package() {
  local bid="$1"
  list_buildings >/dev/null || bad "package buildings list failed"
  if building_present "$bid"; then
    echo "package present for building_id=$bid" | tee -a "$ART/gate19_seed.log"
    return 0
  fi
  echo "WARN: imported package missing for building_id=$bid — seeding" \
    | tee -a "$ART/gate19_seed.log"

  local zip_path=""
  if [[ -n "$PACKAGE_ZIP" && -f "$PACKAGE_ZIP" ]]; then
    zip_path="$PACKAGE_ZIP"
  else
    zip_path="$ART/gate19_seed_BUILDING_100.zip"
    build_seed_zip "$zip_path" | tee -a "$ART/gate19_seed.log"
  fi

  curl -sS --max-time 600 -X POST "$BASE/api/csv/import/package" \
    "${auth[@]}" \
    -H 'Content-Type: application/zip' \
    --data-binary @"$zip_path" \
    | tee "$ART/package_import.json" >/dev/null
  jq -e '.ok == true' "$ART/package_import.json" >/dev/null || {
    echo "FAIL package seed import: $(head -c 800 "$ART/package_import.json")" >&2
    bad "package seed failed for $bid"
  }
  local imported
  imported="$(jq -r '.building_id // empty' "$ART/package_import.json")"
  [[ "$imported" == "$bid" ]] || {
    echo "FAIL seeded building_id=$imported expected $bid" >&2
    bad "package seed building_id mismatch"
  }
  list_buildings >/dev/null || true
  building_present "$bid" || bad "package still missing after seed for $bid"
  echo "PASS seeded package building_id=$bid" | tee -a "$ART/gate19_seed.log"
}

ensure_package "$BUILDING_ID"

JOB_JSON="$ART/job_create.json"
curl -fsS --max-time 60 -X POST "$BASE/api/jobs" \
  "${auth[@]}" \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg b "$BUILDING_ID" '{job_name:"gate19 bundle",site_id:$b}')" \
  >"$JOB_JSON" 2>"$ART/job_create.err" || bad "job create failed"
JOB_ID="$(jq -r '.job.job_id // .job_id // empty' "$JOB_JSON")"
[[ -n "$JOB_ID" ]] || bad "missing job_id"

EXPORT_JSON="$ART/export_create.json"
EXPORT_HTTP="$ART/export_create.http"
# Capture status + body so package_missing is visible (not a bare curl 404).
http_code="$(
  curl -sS --max-time 300 -o "$EXPORT_JSON" -w '%{http_code}' \
    -X POST "$BASE/api/jobs/$JOB_ID/exports" \
    "${auth[@]}" \
    -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg b "$BUILDING_ID" '{building_id:$b,profile:"summary"}')"
)"
echo "$http_code" >"$EXPORT_HTTP"
if [[ "$http_code" != "200" && "$http_code" != "201" ]]; then
  echo "FAIL export create HTTP $http_code body=$(head -c 800 "$EXPORT_JSON")" >&2
  code="$(jq -r '.code // empty' "$EXPORT_JSON" 2>/dev/null || true)"
  err="$(jq -r '.error // empty' "$EXPORT_JSON" 2>/dev/null || true)"
  if [[ "$code" == "package_missing" || "$err" == imported\ package\ not\ found* ]]; then
    bad "export create package_missing for building_id=$BUILDING_ID"
  fi
  bad "export create failed"
fi
EXPORT_ID="$(jq -r '.export.export_id // empty' "$EXPORT_JSON")"
[[ -n "$EXPORT_ID" ]] || bad "missing export_id"

ZIP_PATH="$ART/engineering_bundle.zip"
curl -fsS --max-time 300 \
  "${auth[@]}" \
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
