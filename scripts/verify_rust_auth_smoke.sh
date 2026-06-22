#!/usr/bin/env bash
# Smoke test: generate auth, login as integrator, verify protected routes and RBAC.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

AUTH_PATH="$ROOT/workspace/auth.env.local"
mkdir -p workspace/logs

if [[ ! -f "$AUTH_PATH" ]]; then
  if command -v openfdd_edge >/dev/null 2>&1; then
    openfdd_edge auth init --path "$AUTH_PATH" --force
  elif [[ -x "$ROOT/edge/target/release/openfdd_edge" ]]; then
    "$ROOT/edge/target/release/openfdd_edge" auth init --path "$AUTH_PATH" --force
  else
    (cd edge && cargo run --release --bin openfdd_edge -- auth init --path "$AUTH_PATH" --force)
  fi
fi

chmod 600 "$AUTH_PATH" 2>/dev/null || true

INTEGRATOR_PW="$(grep '^OFDD_INTEGRATOR_PASSWORD=' "$AUTH_PATH" | cut -d= -f2- | tr -d '\r')"
OPERATOR_PW="$(grep '^OFDD_OPERATOR_PASSWORD=' "$AUTH_PATH" | cut -d= -f2- | tr -d '\r')"
AGENT_PW="$(grep '^OFDD_AGENT_PASSWORD=' "$AUTH_PATH" | cut -d= -f2- | tr -d '\r')"

login() {
  local user="$1" pass="$2"
  curl -fsS -X POST http://127.0.0.1:8080/api/auth/login \
    -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg u "$user" --arg p "$pass" '{username:$u,password:$p}')"
}

curl -fsS http://127.0.0.1:8080/api/health | jq -e '.ok == true and .auth_required == true'

INTEGRATOR_TOKEN="$(login integrator "$INTEGRATOR_PW" | jq -r '.token // .access_token')"
curl -fsS http://127.0.0.1:8080/api/health/stack -H "Authorization: Bearer $INTEGRATOR_TOKEN" | jq -e '.ok == true'

OPERATOR_TOKEN="$(login operator "$OPERATOR_PW" | jq -r '.token // .access_token')"
STATUS="$(curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:8080/api/modbus/scan \
  -H "Authorization: Bearer $OPERATOR_TOKEN" -H 'Content-Type: application/json' -d '{}')"
test "$STATUS" = "403"

AGENT_TOKEN="$(login agent "$AGENT_PW" | jq -r '.token // .access_token')"
STATUS="$(curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:8080/api/bacnet/write \
  -H "Authorization: Bearer $AGENT_TOKEN" -H 'Content-Type: application/json' \
  -d '{"approved":true}')"
test "$STATUS" = "403"

curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:8080/api/auth/login \
  -H 'Content-Type: application/json' -d '{"sub":"agent","role":"agent"}' | grep -q '^401$'

curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:8080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg p wrong '{username:"integrator",password:$p}')" | grep -q '^401$'

echo "verify_rust_auth_smoke: OK"
