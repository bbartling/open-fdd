#!/usr/bin/env bash
# Validate a Rust Open-FDD edge site after bootstrap or update.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_rust_site_lib.sh
source "$ROOT/scripts/openfdd_rust_site_lib.sh"

BASE="${OPENFDD_API_BASE:-http://127.0.0.1:8080}"
LIVE_BACNET="${VALIDATE_LIVE_BACNET:-0}"
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
COMPOSE="$(openfdd_rust_resolve_compose_file "$ROOT")"
[[ -f "$COMPOSE" ]] && docker compose -f "$COMPOSE" config >/dev/null

AUTH="$ROOT/workspace/auth.env.local"
check test -d "$ROOT/workspace"
check test -w "$ROOT/workspace"
check test -f "$AUTH"
[[ -f "$AUTH" ]] && chmod 600 "$AUTH" 2>/dev/null || true

openfdd_rust_warn_root_owned_workspace "$ROOT/workspace"

check curl -fsS "${BASE}/api/health"
curl -fsS "${BASE}/api/health" | jq -e '.ok == true' >/dev/null

if [[ -f "$AUTH" ]]; then
  openfdd_rust_login_smoke "$BASE" "$AUTH" || FAIL=1
fi

check curl -fsS "${BASE}/" -o /dev/null
check curl -fsS "${BASE}/app.js" -o /dev/null

TOKEN="$(curl -fsS -X POST "${BASE}/api/auth/login" \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg u "$(grep '^OFDD_INTEGRATOR_USER=' "$AUTH" | cut -d= -f2-)" --arg p "$(grep '^OFDD_INTEGRATOR_PASSWORD=' "$AUTH" | cut -d= -f2-)" '{username:$u,password:$p}')" \
  | jq -r '.token // .access_token')"
check test -n "$TOKEN"
check curl -fsS "${BASE}/api/bacnet/driver/tree" -H "Authorization: Bearer $TOKEN"

if curl -fsS "${BASE}/api/bench/5007/smoke/status" -H "Authorization: Bearer $TOKEN" >/dev/null 2>&1; then
  echo "OK: bench smoke status endpoint present"
fi

if [[ "$LIVE_BACNET" == "1" ]]; then
  echo "Live BACnet: run sudo tcpdump -ni enp3s0 'udp port 47808' -vv during poll"
fi

if [[ "$FAIL" -eq 0 ]]; then
  echo "Validation passed."
else
  echo "Validation failed." >&2
  exit 1
fi
