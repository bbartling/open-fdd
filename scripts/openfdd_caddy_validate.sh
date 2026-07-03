#!/usr/bin/env bash
# Validate bridge health and optional Caddy ingress (HTTP/TLS, headers, auth).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_auth_lib.sh
source "$ROOT/scripts/openfdd_auth_lib.sh"

BRIDGE="${OPENFDD_BRIDGE_BASE:-http://127.0.0.1:8080}"
CADDY_HTTP="${OPENFDD_CADDY_HTTP_BASE:-http://127.0.0.1:80}"
CADDY_TLS="${OPENFDD_CADDY_TLS_BASE:-https://127.0.0.1:443}"
AUTH="${OPENFDD_AUTH_ENV:-$ROOT/workspace/auth.env.local}"

FAIL=0
pass() { echo "PASS: $*"; }
fail() { echo "FAIL: $*" >&2; FAIL=1; }
skip() { echo "SKIP: $*"; }

curl_bridge=(-fsS)
curl_caddy=(-fsS)
curl_tls=(-k -fsS)

caddy_running() {
  docker ps --format '{{.Names}}' 2>/dev/null | grep -qx 'openfdd-caddy'
}

caddy_tls_mode() {
  docker inspect openfdd-caddy --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null \
    | grep -q '^OPENFDD_CADDY_MODE=tls$'
}

check_headers() {
  local url="$1"
  local label="$2"
  local extra="${3:-}"
  local headers
  if [[ "$extra" == tls ]]; then
    headers="$(curl -k -sS -D - -o /dev/null "${url}/" 2>/dev/null || true)"
  else
    headers="$(curl -sS -D - -o /dev/null "${url}/" 2>/dev/null || true)"
  fi
  if [[ -z "$headers" ]]; then
    fail "$label: no response headers"
    return
  fi
  if grep -qi '^x-content-type-options: nosniff' <<<"$headers"; then
    pass "$label: X-Content-Type-Options nosniff"
  else
    fail "$label: missing X-Content-Type-Options nosniff"
  fi
  if grep -qi '^x-frame-options:' <<<"$headers"; then
    pass "$label: X-Frame-Options present"
  else
    fail "$label: missing X-Frame-Options"
  fi
  if grep -qi '^server: caddy' <<<"$headers"; then
    fail "$label: Server header not stripped (caddy visible)"
  else
    pass "$label: Server header stripped or absent"
  fi
}

echo "==> Caddy / bridge validation"

if curl "${curl_bridge[@]}" "${BRIDGE}/api/health" | jq -e '.ok == true' >/dev/null 2>&1; then
  pass "bridge direct ${BRIDGE}/api/health"
else
  fail "bridge direct ${BRIDGE}/api/health"
fi

if ! caddy_running; then
  skip "openfdd-caddy not running — proxy/TLS/header/auth via Caddy skipped"
  if [[ "$FAIL" -eq 0 ]]; then
    echo "Caddy validation complete (bridge-only)."
    exit 0
  fi
  echo "Caddy validation failed." >&2
  exit 1
fi

pass "openfdd-caddy container running"

if curl "${curl_caddy[@]}" "${CADDY_HTTP}/api/health" | jq -e '.ok == true' >/dev/null 2>&1; then
  pass "Caddy :80 proxy ${CADDY_HTTP}/api/health"
else
  fail "Caddy :80 proxy ${CADDY_HTTP}/api/health"
fi

if caddy_tls_mode; then
  loc="$(curl -sS -o /dev/null -w '%{redirect_url}' "${CADDY_HTTP}/api/health" 2>/dev/null || true)"
  code="$(curl -sS -o /dev/null -w '%{http_code}' -L "${CADDY_HTTP}/" 2>/dev/null || true)"
  redir_headers="$(curl -sS -I "${CADDY_HTTP}/" 2>/dev/null | tr -d '\r' || true)"
  if grep -qi '^location: https://' <<<"$redir_headers"; then
    pass "TLS profile: HTTP :80 redirects to HTTPS"
  else
    fail "TLS profile: expected :80 -> https redirect (got code=${code}, loc=${loc})"
  fi
  if curl "${curl_tls[@]}" "${CADDY_TLS}/api/health" | jq -e '.ok == true' >/dev/null 2>&1; then
    pass "Caddy TLS ${CADDY_TLS}/api/health"
  else
    fail "Caddy TLS ${CADDY_TLS}/api/health"
  fi
  check_headers "${CADDY_TLS}" "Caddy TLS" tls
  PROTECTED_BASE="$CADDY_TLS"
  CURL_PROTECT=("${curl_tls[@]}")
else
  skip "caddy-http profile (no TLS redirect check)"
  check_headers "${CADDY_HTTP}" "Caddy HTTP"
  PROTECTED_BASE="$CADDY_HTTP"
  CURL_PROTECT=("${curl_caddy[@]}")
fi

code_unauth="$(curl "${CURL_PROTECT[@]}" -sS -o /dev/null -w '%{http_code}' "${PROTECTED_BASE}/api/health/stack" 2>/dev/null || echo 000)"
if [[ "$code_unauth" == "401" ]]; then
  pass "protected API /api/health/stack requires auth via Caddy (401 without JWT)"
else
  fail "protected API via Caddy expected 401 without JWT, got ${code_unauth}"
fi

if [[ -f "$AUTH" ]]; then
  if token="$(openfdd_auth_login_token "$PROTECTED_BASE" "$AUTH" integrator 2>/dev/null)"; then
    if curl "${CURL_PROTECT[@]}" "${PROTECTED_BASE}/api/health/stack" -H "Authorization: Bearer ${token}" | jq -e '.ok == true' >/dev/null 2>&1; then
      pass "protected API /api/health/stack with integrator JWT via Caddy"
    else
      fail "protected API /api/health/stack with JWT via Caddy"
    fi
  else
    fail "integrator login via Caddy path"
  fi
else
  skip "auth.env.local missing — JWT via Caddy not tested"
fi

if [[ "$FAIL" -eq 0 ]]; then
  echo "Caddy validation passed."
  exit 0
fi
echo "Caddy validation failed." >&2
exit 1
