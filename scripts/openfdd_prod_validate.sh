#!/usr/bin/env bash
# Validate production compose (Rust API + Caddy TLS + auth).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_rust_site_lib.sh
source "$ROOT/scripts/openfdd_rust_site_lib.sh"

HTTPS_PORT="${OPENFDD_HTTPS_PORT:-443}"
HTTP_BASE="${OPENFDD_API_BASE:-https://localhost:${HTTPS_PORT}}"
API_BASE="${HTTP_BASE}/api"
AUTH="$ROOT/workspace/auth.env.local"
FAIL=0

check() {
  if "$@"; then
    echo "OK: $*"
  else
    echo "FAIL: $*" >&2
    FAIL=1
  fi
}

openfdd_rust_check_docker
check test -f "$AUTH"

echo "==> Health (via Caddy, TLS verify skipped for internal cert)"
check curl -kfsS "${API_BASE}/health"
curl -kfsS "${API_BASE}/health" | jq -e '.ok == true and .auth_required == true' >/dev/null

if [[ -f "$AUTH" ]]; then
  INTEGRATOR_PW="$(grep '^OFDD_INTEGRATOR_PASSWORD=' "$AUTH" | cut -d= -f2- | tr -d '\r')"
  TOKEN="$(curl -kfsS -X POST "${API_BASE}/auth/login" \
    -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg p "$INTEGRATOR_PW" '{username:"integrator",password:$p}')" \
    | jq -r '.token // .access_token')"
  check test -n "$TOKEN"
  check test "$TOKEN" != "null"
  check curl -kfsS "${API_BASE}/health/stack" -H "Authorization: Bearer $TOKEN"
  check curl -kfsS "${API_BASE}/bacnet/driver/tree" -H "Authorization: Bearer $TOKEN"
fi

check curl -kfsS "${HTTP_BASE}/" -o /dev/null
check curl -kfsS "${HTTP_BASE}/app.js" -o /dev/null

if docker compose -f "$ROOT/docker-compose.prod.yml" ps --status running | grep -q openfdd-bridge; then
  echo "OK: bridge container running"
else
  echo "FAIL: bridge container not running" >&2
  FAIL=1
fi

if docker compose -f "$ROOT/docker-compose.prod.yml" ps --status running | grep -q openfdd-caddy; then
  echo "OK: caddy container running"
else
  echo "FAIL: caddy container not running" >&2
  FAIL=1
fi

if [[ "$FAIL" -eq 0 ]]; then
  echo "Production validation passed."
else
  echo "Production validation failed." >&2
  exit 1
fi
