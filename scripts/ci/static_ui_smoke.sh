#!/usr/bin/env bash
# Real-stack smoke for static product UI on central /app/ (no image build).
# Expects openfdd-central listening on OPENFDD_STATIC_UI_BASE (default 127.0.0.1:8080)
# with OPENFDD_STATIC_PRODUCT_UI=1.
set -euo pipefail

BASE="${OPENFDD_STATIC_UI_BASE:-http://127.0.0.1:8080}"
ADMIN_USER="${OPENFDD_ADMIN_USER:-admin}"
ADMIN_PASS="${OPENFDD_ADMIN_PASSWORD:-}"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

echo "== static UI smoke base=$BASE =="

health="$(curl -fsS "$BASE/api/health")" || fail "GET /api/health"
echo "$health" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("service")=="openfdd-central", d' \
  || fail "health service field"
echo "OK /api/health"

csp="$(curl -fsSI "$BASE/app/" | tr -d '\r' | awk -F': ' 'tolower($1)=="content-security-policy"{print $2; exit}')"
[[ -n "$csp" ]] || fail "missing Content-Security-Policy on /app/"
case "$csp" in
  *unsafe-inline*|*unsafe-eval*) fail "CSP must not allow unsafe-inline or unsafe-eval" ;;
esac
echo "OK /app/ CSP"

for path in \
  /app/ \
  /app/assets/js/app.js \
  /app/assets/js/operations-tab.js \
  /app/assets/vendor/echarts.esm.min.js; do
  code="$(curl -fsS -o /dev/null -w '%{http_code}' "$BASE$path")"
  [[ "$code" == "200" ]] || fail "GET $path HTTP $code"
done
echo "OK static assets"

if [[ -n "$ADMIN_PASS" ]]; then
  TOKEN="$(
    curl -fsS -X POST "$BASE/api/auth/login" \
      -H "Content-Type: application/json" \
      -d "{\"username\":\"$ADMIN_USER\",\"password\":\"$ADMIN_PASS\"}" \
      | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("token") or d.get("access_token") or "")'
  )"
  [[ ${#TOKEN} -ge 20 ]] || fail "admin login for smoke APIs"
  me="$(curl -fsS "$BASE/api/auth/me" -H "Authorization: Bearer $TOKEN")"
  echo "$me" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("ok") is True, d' \
    || fail "/api/auth/me"
  mv="$(curl -fsS -X POST "$BASE/api/analytics/mv" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d @- <<'JSON'
{"query_version":"mv-change-point-v1","series":{"baseline_end":"2023-12","dd_kind":"hdd","rows":[{"period":"2023-01","energy":2100,"degree_days":800},{"period":"2023-02","energy":1900,"degree_days":700}]}}
JSON
)"
  echo "$mv" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert "points" in d or d.get("ok") is not False, d' \
    || fail "POST /api/analytics/mv demo"
  echo "OK authenticated APIs (auth/me + analytics/mv)"
else
  echo "SKIP authenticated API probes (OPENFDD_ADMIN_PASSWORD unset)"
fi

echo "PASS static_ui_smoke.sh"
