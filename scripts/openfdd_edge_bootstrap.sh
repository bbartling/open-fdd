#!/usr/bin/env bash
# LEGACY: local source-checkout bootstrap (build from Dockerfile).
# For GHCR production install use: scripts/openfdd_rust_edge_bootstrap.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

mkdir -p workspace/{auth,reports/rcx,data/rules,data/historian,backups,memory,logs}
if [ ! -f .env ]; then
  SECRET="$(openssl rand -hex 32 2>/dev/null || date +%s%N)"
  cat > .env <<EOF
OPENFDD_JWT_SECRET=${SECRET}
OPENFDD_AUTH_MODE=jwt
OPENFDD_BIND=0.0.0.0
OPENFDD_EDGE_PROFILE=rust
EOF
fi

docker compose up -d --build

curl -sf http://127.0.0.1:8080/api/health
echo
TOKEN="$(curl -s -X POST http://127.0.0.1:8080/api/auth/login -H 'Content-Type: application/json' -d '{"sub":"bootstrap","role":"agent"}' | sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p')"
test -n "$TOKEN"
curl -sf http://127.0.0.1:8080/api/health/stack -H "Authorization: Bearer $TOKEN"
echo
