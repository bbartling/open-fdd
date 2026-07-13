#!/usr/bin/env bash
# Backend API check — health, auth, protected routes, ZIP inspect, error cases.
#
#   ./scripts/openfdd_api_check.sh
#   ./scripts/openfdd_api_check.sh --base-url http://127.0.0.1:8080
#
# Artifacts: workspace/logs/api_check_<timestamp>/
# Exit 1 if any check fails.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_auth_lib.sh
source "$ROOT/scripts/openfdd_auth_lib.sh"

BASE="${OPENFDD_API_BASE:-${OPENFDD_BRIDGE_BASE:-http://127.0.0.1:8080}}"
AUTH="${OPENFDD_AUTH_ENV:-$ROOT/workspace/auth.env.local}"
ZIP_FIXTURE="${OPENFDD_ZIP_FIXTURE:-$ROOT/edge/tests/fixtures/zip_package/tiny_package.zip}"
CURL_TLS=()
PASS=0
FAIL=0
WARN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base-url) BASE="${2:?}"; shift 2 ;;
    -h|--help)
      sed -n '2,10p' "$0"
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

if [[ "$BASE" == https://* ]]; then CURL_TLS=(-k); fi

ARTIFACT="$ROOT/workspace/logs/api_check_$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$ARTIFACT"

ok() { echo "  OK  $1"; PASS=$((PASS + 1)); }
fail() { echo "  FAIL $1" >&2; FAIL=$((FAIL + 1)); }
warn() { echo "  WARN $1" >&2; WARN=$((WARN + 1)); }

save_body() {
  local name="$1" body="$2"
  printf '%s' "$body" >"$ARTIFACT/${name}.json"
}

echo "==> API check at $BASE"
echo "    artifacts: $ARTIFACT"

# --- Public health ---
code="$(curl "${CURL_TLS[@]}" -sS -o "$ARTIFACT/health.json" -w '%{http_code}' "$BASE/api/health" || echo 000)"
if [[ "$code" != "200" ]]; then
  fail "GET /api/health HTTP $code — is the edge running? Try ./scripts/openfdd_cargo_up.sh"
  echo "PASS=$PASS FAIL=$FAIL WARN=$WARN" | tee "$ARTIFACT/summary.txt"
  exit 1
fi
if ! jq -e '.ok == true' "$ARTIFACT/health.json" >/dev/null; then
  fail "/api/health ok!=true"
else
  ver="$(jq -r '.version // .image_tag // "?"' "$ARTIFACT/health.json")"
  auth_req="$(jq -r '.auth_required // false' "$ARTIFACT/health.json")"
  ok "/api/health (version=$ver auth_required=$auth_req)"
fi

# --- Negative auth ---
code="$(curl "${CURL_TLS[@]}" -sS -o "$ARTIFACT/no_jwt.json" -w '%{http_code}' \
  "$BASE/api/dashboard/summary")"
if [[ "$code" == "401" ]]; then
  ok "protected route without JWT → 401"
else
  fail "protected route without JWT → HTTP $code (expected 401)"
fi

code="$(curl "${CURL_TLS[@]}" -sS -o "$ARTIFACT/bad_login.json" -w '%{http_code}' \
  -X POST "$BASE/api/auth/login" \
  -H 'Content-Type: application/json' \
  -d '{"username":"integrator","password":"wrong-password"}')"
if [[ "$code" == "401" ]] && jq -e '.ok == false' "$ARTIFACT/bad_login.json" >/dev/null 2>&1; then
  ok "invalid password → 401"
else
  fail "invalid password → HTTP $code"
fi

code="$(curl "${CURL_TLS[@]}" -sS -o "$ARTIFACT/malformed_jwt.json" -w '%{http_code}' \
  "$BASE/api/health/stack" -H 'Authorization: Bearer not.a.jwt')"
if [[ "$code" == "401" ]]; then
  ok "malformed JWT → 401"
else
  fail "malformed JWT → HTTP $code (expected 401)"
fi

# --- Login ---
if [[ ! -f "$AUTH" ]]; then
  fail "missing $AUTH — run ./scripts/openfdd_auth_init.sh --show-secrets"
  echo "PASS=$PASS FAIL=$FAIL WARN=$WARN" | tee "$ARTIFACT/summary.txt"
  exit 1
fi

token="$(openfdd_auth_login_token "$BASE" "$AUTH" integrator)" || token=""
if [[ -z "$token" || "$token" == "null" ]]; then
  fail "integrator login (check bootstrap_credentials.once.txt)"
  echo "PASS=$PASS FAIL=$FAIL WARN=$WARN" | tee "$ARTIFACT/summary.txt"
  exit 1
fi
ok "integrator login"

auth_get() {
  local name="$1" path="$2" expect_ok="${3:-1}"
  local out="$ARTIFACT/${name}.json"
  local code
  code="$(curl "${CURL_TLS[@]}" -sS -o "$out" -w '%{http_code}' \
    "${BASE}${path}" -H "Authorization: Bearer $token")" || code=000
  if [[ "$code" == "500" ]]; then
    fail "GET $path → HTTP 500 — $(jq -r '.error // .message // empty' "$out" 2>/dev/null | head -c 120)"
    return
  fi
  if [[ "$code" -ge 400 ]]; then
    fail "GET $path → HTTP $code — $(jq -r '.error // empty' "$out" 2>/dev/null | head -c 120)"
    return
  fi
  if [[ "$expect_ok" == "1" ]] && jq -e 'has("ok") and .ok == false' "$out" >/dev/null 2>&1; then
    fail "GET $path ok:false — $(jq -r '.error // "unknown"' "$out")"
    return
  fi
  ok "GET $path ($code)"
}

auth_get me /api/auth/me
auth_get stack /api/health/stack
auth_get dashboard_summary /api/dashboard/summary
auth_get dashboard_analytics /api/dashboard/analytics
auth_get building_status /api/building/status
auth_get building_snapshot /api/building/snapshot 0
auth_get fdd_rules /api/fdd/rules 0
auth_get fdd_rules_legacy /api/fdd-rules 0
auth_get datasets /api/datasets 0
auth_get data_mgmt /api/data-management/summary
auth_get host /api/host/stats 0
auth_get export_meta /api/export/meta 0
auth_get model_haystack /api/model/haystack 0
auth_get timeseries_sites /api/timeseries/sites 0
auth_get validation_status /api/validation-runs/current/status 0

# Registry count (Phase 1 expects a non-empty catalog when assets are present)
if [[ -f "$ARTIFACT/fdd_rules.json" ]]; then
  count="$(jq -r '(.rules // .entries // .items // []) | length' "$ARTIFACT/fdd_rules.json" 2>/dev/null || echo 0)"
  if [[ "${count:-0}" -gt 0 ]]; then
    ok "FDD rule catalog count=$count"
  else
    warn "FDD rule catalog empty or unexpected shape (count=$count)"
  fi
fi

# --- ZIP package (multipart — same path as React FormData) ---
if [[ -f "$ZIP_FIXTURE" ]]; then
  code="$(curl "${CURL_TLS[@]}" -sS -o "$ARTIFACT/zip_inspect.json" -w '%{http_code}' \
    -X POST "$BASE/api/csv/import/zip/inspect" \
    -H "Authorization: Bearer $token" \
    -F "file=@${ZIP_FIXTURE};type=application/zip")" || code=000
  if [[ "$code" == "200" ]] && jq -e '.ok == true' "$ARTIFACT/zip_inspect.json" >/dev/null 2>&1; then
    pkg="$(jq -r '.package_id' "$ARTIFACT/zip_inspect.json")"
    ok "ZIP multipart inspect ($pkg)"
    code="$(curl "${CURL_TLS[@]}" -sS -o "$ARTIFACT/zip_plan.json" -w '%{http_code}' \
      -X POST "$BASE/api/csv/import/zip/plan" \
      -H "Authorization: Bearer $token" \
      -H 'Content-Type: application/json' \
      -d "$(jq -nc --arg id "$pkg" '{package_id:$id}')")" || code=000
    if [[ "$code" == "200" ]] && jq -e '.ok == true' "$ARTIFACT/zip_plan.json" >/dev/null 2>&1; then
      ok "ZIP plan session=$(jq -r '.session_id' "$ARTIFACT/zip_plan.json")"
    else
      fail "ZIP plan → HTTP $code — $(jq -r '.error // empty' "$ARTIFACT/zip_plan.json")"
    fi
  else
    fail "ZIP multipart inspect → HTTP $code — $(jq -r '.error // empty' "$ARTIFACT/zip_inspect.json")"
  fi
else
  warn "ZIP fixture missing ($ZIP_FIXTURE) — skip package check"
fi

# --- Logout ---
code="$(curl "${CURL_TLS[@]}" -sS -o "$ARTIFACT/logout.json" -w '%{http_code}' \
  -X POST "$BASE/api/auth/logout" \
  -H "Authorization: Bearer $token" \
  -H 'Content-Type: application/json' -d '{}')" || code=000
if [[ "$code" == "200" ]]; then
  ok "POST /api/auth/logout"
else
  fail "logout → HTTP $code"
fi

jq -nc \
  --arg finished "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg base "$BASE" \
  --arg dir "$ARTIFACT" \
  --argjson pass "$PASS" \
  --argjson fail "$FAIL" \
  --argjson warn "$WARN" \
  '{finished_at:$finished,base:$base,artifact_dir:$dir,pass:$pass,fail:$fail,warn:$warn}' \
  >"$ARTIFACT/final_report.json"

echo
echo "API check: pass=$PASS fail=$FAIL warn=$WARN"
echo "Report: $ARTIFACT/final_report.json"
if [[ "$FAIL" -ne 0 ]]; then
  echo "API check FAILED" >&2
  exit 1
fi
echo "API check PASS"
