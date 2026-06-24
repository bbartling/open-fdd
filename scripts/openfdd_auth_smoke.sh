#!/usr/bin/env bash
# Login smoke test — verifies workspace/auth.env.local credentials against a running bridge.
# Does not print passwords or tokens.
#
#   OPENFDD_AUTH_SMOKE_PASSWORD='...' ./scripts/openfdd_auth_smoke.sh
#   ./scripts/openfdd_auth_smoke.sh --credentials workspace/bootstrap_credentials.once.txt
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE="${OPENFDD_BRIDGE_BASE:-http://127.0.0.1:8080}"
CRED_FILE=""
PASSWORD="${OPENFDD_AUTH_SMOKE_PASSWORD:-}"

usage() {
  cat <<'EOF'
Usage: scripts/openfdd_auth_smoke.sh [--credentials FILE] [--base URL]

Tests POST /api/auth/login and GET /api/auth/me for operator, integrator, and agent.
Provide password via OPENFDD_AUTH_SMOKE_PASSWORD or a bootstrap credentials file (username: password lines).
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --credentials) CRED_FILE="$2"; shift 2 ;;
    --base) BASE="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "$PASSWORD" && -n "$CRED_FILE" ]]; then
  [[ -f "$CRED_FILE" ]] || { echo "Missing credentials file: $CRED_FILE" >&2; exit 1; }
fi

lookup_password() {
  local user="$1"
  if [[ -n "$PASSWORD" ]]; then
    printf '%s' "$PASSWORD"
    return 0
  fi
  if [[ -n "$CRED_FILE" ]]; then
    local line
    line="$(grep -E "^${user}:" "$CRED_FILE" | head -1 || true)"
    [[ -n "$line" ]] || return 1
    printf '%s' "${line#*: }"
    return 0
  fi
  return 1
}

login_as() {
  local user="$1"
  local pass
  pass="$(lookup_password "$user")" || {
    echo "FAIL: no password for $user (set OPENFDD_AUTH_SMOKE_PASSWORD or --credentials)" >&2
    return 1
  }
  if [[ "$pass" == \$2b\$* ]]; then
    echo "FAIL: $user password looks like a bcrypt hash — use plaintext from bootstrap, not auth.env.local" >&2
    return 1
  fi
  local body token me_role
  body="$(python3 -c 'import json,sys; print(json.dumps({"username":sys.argv[1],"password":sys.argv[2]}))' "$user" "$pass")"
  local resp
  resp="$(curl -fsS -X POST "$BASE/api/auth/login" -H 'Content-Type: application/json' -d "$body")" || {
    echo "FAIL: login HTTP error for $user" >&2
    return 1
  }
  if ! printf '%s' "$resp" | python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get('ok') else 1)"; then
    echo "FAIL: login rejected for $user" >&2
    return 1
  fi
  token="$(printf '%s' "$resp" | python3 -c "import json,sys; print(json.load(sys.stdin).get('token',''))")"
  me_role="$(curl -fsS "$BASE/api/auth/me" -H "Authorization: Bearer $token" | python3 -c "import json,sys; print(json.load(sys.stdin).get('role',''))")"
  if [[ "$me_role" != "$user" && ! ( "$user" == "integrator" && "$me_role" == "integrator" ) ]]; then
    if [[ "$me_role" != "$user" ]]; then
      echo "FAIL: /api/auth/me role mismatch for $user (got $me_role)" >&2
      return 1
    fi
  fi
  echo "OK: $user login + /api/auth/me"
}

curl -fsS "$BASE/health" >/dev/null || { echo "Bridge not healthy at $BASE" >&2; exit 1; }

if [[ -n "$PASSWORD" ]]; then
  login_as integrator
else
  CRED_FILE="${CRED_FILE:-$ROOT/workspace/bootstrap_credentials.once.txt}"
  for role in operator integrator agent; do
    login_as "$role"
  done
fi

echo "Auth smoke passed at $BASE"
