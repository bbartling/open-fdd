#!/usr/bin/env bash
# Programmatic UI smoke — visits key tabs, fails on HTTP 500 or obvious API errors.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_auth_lib.sh
source "$ROOT/scripts/openfdd_auth_lib.sh"

BASE="${OPENFDD_API_BASE:-http://127.0.0.1:8080}"
AUTH="${OPENFDD_AUTH_ENV:-$ROOT/workspace/auth.env.local}"
ARTIFACT="${OPENFDD_UI_SMOKE_ARTIFACT:-$ROOT/workspace/logs/ui_smoke_$(date -u +%Y%m%dT%H%M%SZ)}"
CURL_TLS=()
if [[ "$BASE" == https://* ]]; then CURL_TLS=(-k); fi

mkdir -p "$ARTIFACT"
fail=0

token="$(openfdd_auth_login_token "$BASE" "$AUTH" integrator)" || exit 1

check_api() {
  local name="$1"
  local path="$2"
  local method="${3:-GET}"
  local out="$ARTIFACT/${name//\//_}.json"
  local code
  code="$(curl "${CURL_TLS[@]}" -sS -o "$out" -w '%{http_code}' \
    -X "$method" "${BASE}${path}" \
    -H "Authorization: Bearer $token" \
    -H 'Content-Type: application/json' \
    ${4:+-d "$4"})"
  if [[ "$code" == 500 ]]; then
    echo "FAIL: $name HTTP 500" >&2
    fail=1
    return
  fi
  if [[ "$code" -ge 400 && "$path" != *"/api/auth/"* ]]; then
    echo "WARN: $name HTTP $code" >&2
  fi
  jq -e '.ok != false or .error == null' "$out" >/dev/null 2>&1 || {
    if jq -e '.ok == false' "$out" >/dev/null 2>&1; then
      echo "FAIL: $name returned ok:false — $(jq -r '.error // .message // "unknown"' "$out")" >&2
      fail=1
    fi
  }
  echo "OK: $name ($code)"
}

echo "UI smoke artifact: $ARTIFACT"
check_api health /api/health
check_api stack-health /api/health/stack
check_api validation-status /api/validation-runs/current/status
check_api json-api-sources /api/json-api/sources
check_api model-haystack /api/model/haystack
check_api fdd-rules /api/fdd-rules
check_api historian-status /api/historian/validation/status
check_api data-management /api/data-management/summary
check_api export-meta /api/export/meta
check_api reports-templates /api/reports/templates
check_api reports-draft /api/reports/draft POST '{"template_id":"validation-summary","title":"UI Smoke Report"}'

report_id="$(jq -r '.report_id // empty' "$ARTIFACT/reports-draft.json")"
if [[ -n "$report_id" ]]; then
  check_api report-get "/api/reports/${report_id}"
  check_api report-render "/api/reports/${report_id}/render/pdf" POST '{}'
  pdf_code="$(curl "${CURL_TLS[@]}" -sS -o "$ARTIFACT/report.pdf" -w '%{http_code}' \
    "${BASE}/api/reports/${report_id}/download.pdf" \
    -H "Authorization: Bearer $token")"
  if [[ "$pdf_code" != 200 ]]; then
    echo "FAIL: report PDF download HTTP $pdf_code" >&2
    fail=1
  elif [[ ! -s "$ARTIFACT/report.pdf" ]]; then
    echo "FAIL: report PDF empty" >&2
    fail=1
  else
    echo "OK: report PDF ($(wc -c <"$ARTIFACT/report.pdf" | tr -d ' ') bytes)"
  fi
fi

# Static SPA routes should return HTML (no 500 from bridge)
for route in / /login /plot /model /sql-fdd /json-api /data-management /haystack /bacnet /modbus /live-fdd-validation /reports; do
  code="$(curl "${CURL_TLS[@]}" -sS -o "$ARTIFACT/route$(echo "$route" | tr '/' '_').html" -w '%{http_code}' "${BASE}${route}")"
  if [[ "$code" == 500 ]]; then
    echo "FAIL: route $route HTTP 500" >&2
    fail=1
  else
    echo "OK: route $route ($code)"
  fi
done

jq -nc --arg finished "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg dir "$ARTIFACT" --argjson fail "$fail" \
  '{finished_at:$finished,artifact_dir:$dir,failed:$fail}' >"$ARTIFACT/final_report.json"

if [[ "$fail" -ne 0 ]]; then
  echo "UI smoke FAILED — see $ARTIFACT" >&2
  exit 1
fi
echo "UI smoke PASS — $ARTIFACT"
