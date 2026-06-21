#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

./scripts/openfdd_site_backup.sh >/dev/null
docker compose pull || true
docker compose up -d --build --force-recreate
curl -sf http://127.0.0.1:8080/api/health >/dev/null
TOKEN="$(curl -s -X POST http://127.0.0.1:8080/api/auth/login -H 'Content-Type: application/json' -d '{"sub":"update","role":"agent"}' | sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p')"
curl -sf http://127.0.0.1:8080/api/health/stack -H "Authorization: Bearer $TOKEN" >/dev/null
echo "Open-FDD Rust Edge update validated."
