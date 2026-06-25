#!/usr/bin/env bash
# Login smoke test — verifies workspace credentials against a running bridge.
# Does not print passwords or tokens.
#
#   ./scripts/openfdd_auth_smoke.sh
#   OPENFDD_BRIDGE_BASE=http://127.0.0.1:8080 ./scripts/openfdd_auth_smoke.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_auth_lib.sh
source "$ROOT/scripts/openfdd_auth_lib.sh"

BASE="${OPENFDD_BRIDGE_BASE:-http://127.0.0.1:8080}"
AUTH="${OPENFDD_AUTH_ENV:-$ROOT/workspace/auth.env.local}"
CRED_FILE="${OPENFDD_AUTH_CREDENTIALS:-$ROOT/workspace/bootstrap_credentials.once.txt}"
PASSWORD="${OPENFDD_AUTH_SMOKE_PASSWORD:-}"

usage() {
  cat <<'EOF'
Usage: scripts/openfdd_auth_smoke.sh [--base URL]

Tests POST /api/auth/login and GET /api/auth/me for operator, integrator, and agent.

Password resolution (in order):
  1. OPENFDD_AUTH_SMOKE_PASSWORD (single password for integrator-only quick test)
  2. OPENFDD_{ROLE}_PASSWORD env vars
  3. workspace/bootstrap_credentials.once.txt (integrator: ..., operator: ..., agent: ...)
  4. Legacy plaintext keys in auth.env.local

auth.env.local stores bcrypt HASHES — never use OFDD_*_PASSWORD_HASH as the login password.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base) BASE="$2"; shift 2 ;;
    --credentials) CRED_FILE="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

login_as() {
  local role="$1"
  local pass=""
  if [[ -n "$PASSWORD" ]]; then
    pass="$PASSWORD"
  else
    pass="$(openfdd_auth_plaintext_password "$AUTH" "$role" 2>/dev/null || true)"
    if [[ -z "$pass" && -f "$CRED_FILE" ]]; then
      pass="$(grep -E "^${role}:" "$CRED_FILE" | head -1 | cut -d: -f2- | sed 's/^ //' || true)"
    fi
  fi
  if [[ -z "$pass" ]]; then
    echo "FAIL: no plaintext password for $role" >&2
    echo "  Run: ./scripts/openfdd_auth_init.sh --rotate --all --show-secrets --restart" >&2
    return 1
  fi
  if [[ "$pass" == \$2b\$* ]]; then
    echo "FAIL: $role password looks like a bcrypt hash — use plaintext from bootstrap handoff" >&2
    return 1
  fi
  local resp token me_role body
  body="$(jq -nc --arg u "$role" --arg p "$pass" '{username:$u,password:$p}')"
  if ! resp="$(curl -fsS -X POST "$BASE/api/auth/login" -H 'Content-Type: application/json' -d "$body")"; then
    echo "FAIL: login HTTP error for $role" >&2
    return 1
  fi
  if ! jq -e '.ok == true or .token != null or .access_token != null' <<<"$resp" >/dev/null; then
    local err
    err="$(jq -r '.error // "invalid credentials"' <<<"$resp")"
    echo "FAIL: login rejected for $role — $err" >&2
    return 1
  fi
  token="$(jq -r '.token // .access_token // empty' <<<"$resp")"
  me_role="$(curl -fsS "$BASE/api/auth/me" -H "Authorization: Bearer $token" | jq -r '.role // .principal.role // empty')"
  if [[ -n "$me_role" && "$me_role" != "$role" ]]; then
    echo "FAIL: /api/auth/me role mismatch for $role (got $me_role)" >&2
    return 1
  fi
  echo "OK: $role login + /api/auth/me"
}

curl -fsS "$BASE/health" >/dev/null || { echo "Bridge not healthy at $BASE" >&2; exit 1; }

if [[ -n "$PASSWORD" ]]; then
  login_as integrator
else
  for role in operator integrator agent; do
    login_as "$role"
  done
fi

# Dashboard summary endpoint (authenticated)
token="$(openfdd_auth_login_token "$BASE" "$AUTH" integrator")"
curl -fsS "$BASE/api/building/snapshot" -H "Authorization: Bearer $token" >/dev/null
echo "OK: /api/building/snapshot"

echo "Auth smoke passed at $BASE"
