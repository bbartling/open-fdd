#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

./scripts/openfdd_site_backup.sh >/dev/null
docker compose pull || true
docker compose up -d --build --force-recreate
curl -sf http://127.0.0.1:8080/api/health >/dev/null

AUTH_PATH="$ROOT/workspace/auth.env.local"
test -f "$AUTH_PATH"
INTEGRATOR_PW="$(grep '^OFDD_INTEGRATOR_PASSWORD=' "$AUTH_PATH" | cut -d= -f2- | tr -d '\r')"
TOKEN="$(curl -s -X POST http://127.0.0.1:8080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg u integrator --arg p "$INTEGRATOR_PW" '{username:$u,password:$p}')" | jq -r '.token // .access_token')"
test -n "$TOKEN"
curl -sf http://127.0.0.1:8080/api/health/stack -H "Authorization: Bearer $TOKEN" >/dev/null
echo "Open-FDD Rust Edge update validated."
