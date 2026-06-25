#!/usr/bin/env bash
# Lightweight UI inspection smoke — API + SPA routes, no long validation or field hardware.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_auth_lib.sh
source "$ROOT/scripts/openfdd_auth_lib.sh"

BASE="${OPENFDD_API_BASE:-http://127.0.0.1:8080}"
AUTH="${OPENFDD_AUTH_ENV:-$ROOT/workspace/auth.env.local}"
ARTIFACT="${OPENFDD_UI_SMOKE_ARTIFACT:-$ROOT/workspace/logs/ui_smoke_$(date -u +%Y%m%dT%H%M%SZ)}"
CHECK_REPORTS="${OPENFDD_UI_SMOKE_REPORTS:-1}"
CURL_TLS=()
if [[ "$BASE" == https://* ]]; then CURL_TLS=(-k); fi

mkdir -p "$ARTIFACT"
fail=0

if [[ ! -f "$AUTH" ]]; then
  echo "ERROR: missing $AUTH — run ./scripts/openfdd_inspection_build.sh first" >&2
  exit 1
fi

token="$(openfdd_auth_login_token "$BASE" "$AUTH" integrator)" || {
  echo "ERROR: integrator login failed — use plaintext from workspace/bootstrap_credentials.once.txt" >&2
  echo "       auth.env.local stores bcrypt hashes only; do not paste OFDD_*_PASSWORD_HASH as password." >&2
  exit 1
}

check_api() {
  local name="$1"
  local path="$2"
  local method="${3:-GET}"
  local data="${4:-}"
  local out="$ARTIFACT/${name//\//_}.json"
  local code
  if [[ -n "$data" ]]; then
    code="$(curl "${CURL_TLS[@]}" -sS -o "$out" -w '%{http_code}' \
      -X "$method" "${BASE}${path}" \
      -H "Authorization: Bearer $token" \
      -H 'Content-Type: application/json' \
      -d "$data")"
  else
    code="$(curl "${CURL_TLS[@]}" -sS -o "$out" -w '%{http_code}' \
      -X "$method" "${BASE}${path}" \
      -H "Authorization: Bearer $token")"
  fi
  if [[ "$code" == 500 ]]; then
    echo "FAIL: $name HTTP 500" >&2
    fail=1
    return
  fi
  if [[ "$code" -ge 400 ]]; then
    echo "FAIL: $name HTTP $code" >&2
    fail=1
    return
  fi
  if jq -e '.ok == false' "$out" >/dev/null 2>&1; then
    echo "FAIL: $name ok:false — $(jq -r '.error // "unknown"' "$out")" >&2
    fail=1
    return
  fi
  echo "OK: $name ($code)"
}

assert_dashboard_summary() {
  local out="$ARTIFACT/_api_dashboard_summary.json"
  if [[ ! -f "$out" ]]; then
    echo "FAIL: dashboard summary artifact missing" >&2
    fail=1
    return
  fi
  if ! jq -e '.model_coverage.equipment_count != null and .model_coverage.point_count != null' "$out" >/dev/null; then
    echo "FAIL: dashboard summary missing model_coverage counts" >&2
    fail=1
    return
  fi
  if ! jq -e '.faults != null and .historian_health != null' "$out" >/dev/null; then
    echo "FAIL: dashboard summary missing faults or historian sections" >&2
    fail=1
    return
  fi
  echo "OK: dashboard summary shape"
}

assert_dashboard_analytics() {
  local out="$ARTIFACT/_api_dashboard_analytics.json"
  if [[ ! -f "$out" ]]; then
    echo "FAIL: dashboard analytics artifact missing" >&2
    fail=1
    return
  fi
  if ! jq -e '.rule_health.rule_count != null' "$out" >/dev/null; then
    echo "FAIL: dashboard analytics missing rule_health.rule_count" >&2
    fail=1
    return
  fi
  echo "OK: dashboard analytics shape"
}

check_route() {
  local route="$1"
  local out="$ARTIFACT/route$(echo "$route" | tr '/' '_').html"
  local code
  code="$(curl "${CURL_TLS[@]}" -sS -o "$out" -w '%{http_code}' "${BASE}${route}")"
  if [[ "$code" == 500 ]]; then
    echo "FAIL: route $route HTTP 500" >&2
    fail=1
  elif [[ "$code" -ge 400 && "$route" != "/login" ]]; then
    echo "WARN: route $route HTTP $code" >&2
  else
    echo "OK: route $route ($code)"
  fi
}

echo "UI inspection smoke → $ARTIFACT"
check_api public-health /api/health
check_api auth-me /api/auth/me
check_api building-snapshot /api/building/snapshot
check_api building-status /api/building/status
check_api dashboard-summary /api/dashboard/summary
check_api dashboard-analytics /api/dashboard/analytics
check_api stack-health /api/health/stack
check_api json-api-sources /api/json-api/sources
check_api model-haystack /api/model/haystack
check_api fdd-rules /api/fdd-rules
check_api historian-status /api/historian/validation/status
check_api data-management /api/data-management/summary
check_api export-meta /api/export/meta
check_api host-stats /api/host/stats
check_api modbus-poll /api/modbus/poll/status
check_api modbus-tree /api/modbus/driver/tree
check_api json-api-poll /api/json-api/poll/status
check_api json-api-tree /api/json-api/driver/tree
check_api model-equipment "/api/model/sites/site%3Ademo/equipment"

if [[ "$CHECK_REPORTS" == "1" ]]; then
  check_api reports-templates /api/reports/templates
fi

for route in \
  / \
  /login \
  /bacnet \
  /modbus \
  /haystack \
  /json-api \
  /model \
  /sql-fdd \
  /plot \
  /reports \
  /exports \
  /host \
  /data-management \
  /live-fdd-validation; do
  check_route "$route"
done

assert_dashboard_summary
assert_dashboard_analytics

jq -nc \
  --arg finished "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg dir "$ARTIFACT" \
  --arg base "$BASE" \
  --argjson fail "$fail" \
  '{finished_at:$finished,artifact_dir:$dir,base:$base,failed:$fail,mode:"ui_inspection_smoke"}' \
  >"$ARTIFACT/final_report.json"

if [[ "$fail" -ne 0 ]]; then
  echo "UI inspection smoke FAILED — see $ARTIFACT" >&2
  exit 1
fi
echo "UI inspection smoke PASS — $ARTIFACT"
