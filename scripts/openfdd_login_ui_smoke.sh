#!/usr/bin/env bash
# Login smoke — every role via the same API the UI uses, plus SPA health.
#
#   ./scripts/openfdd_login_ui_smoke.sh
#   OPENFDD_BRIDGE_BASE=https://192.168.204.55 ./scripts/openfdd_login_ui_smoke.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_auth_lib.sh
source "$ROOT/scripts/openfdd_auth_lib.sh"

BASE="${OPENFDD_BRIDGE_BASE:-http://127.0.0.1:8080}"
AUTH="${OPENFDD_AUTH_ENV:-$ROOT/workspace/auth.env.local}"
CRED_FILE="${OPENFDD_AUTH_CREDENTIALS:-$ROOT/workspace/bootstrap_credentials.once.txt}"
CURL_TLS=()
if [[ "$BASE" == https://* ]]; then CURL_TLS=(-k); fi

fail=0

login_role() {
  local role="$1"
  local pass
  pass="$(openfdd_auth_plaintext_password "$AUTH" "$role")" || {
    echo "FAIL: no plaintext for $role — run ./scripts/openfdd_auth_init.sh --rotate --all --show-secrets --restart" >&2
    return 1
  }
  if [[ ${#pass} -gt 20 ]]; then
    echo "WARN: $role password length ${#pass} — expected ~14 chars after rotate" >&2
  fi
  if [[ "$pass" == \$2b\$* ]]; then
    echo "FAIL: $role password looks like bcrypt hash" >&2
    return 1
  fi
  local body resp token me_role code
  body="$(jq -nc --arg u "$role" --arg p "$pass" '{username:$u,password:$p}')"
  resp="$(curl "${CURL_TLS[@]}" -sS -X POST "$BASE/api/auth/login" \
    -H 'Content-Type: application/json' -d "$body")" || {
    echo "FAIL: $role login HTTP error" >&2
    return 1
  }
  if ! jq -e '.ok == true' <<<"$resp" >/dev/null; then
    echo "FAIL: $role login rejected — $(jq -r '.error // "invalid credentials"' <<<"$resp")" >&2
    return 1
  fi
  token="$(jq -r '.token // .access_token // empty' <<<"$resp")"
  if [[ -z "$token" ]]; then
    echo "FAIL: $role login missing token/access_token" >&2
    return 1
  fi
  me_role="$(curl "${CURL_TLS[@]}" -fsS "$BASE/api/auth/me" \
    -H "Authorization: Bearer $token" | jq -r '.role // .principal.role // empty')"
  if [[ -n "$me_role" && "$me_role" != "$role" ]]; then
    echo "FAIL: $role /api/auth/me role mismatch (got $me_role)" >&2
    return 1
  fi
  code="$(curl "${CURL_TLS[@]}" -sS -o /dev/null -w '%{http_code}' \
    "$BASE/api/dashboard/summary" -H "Authorization: Bearer $token")"
  if [[ "$code" != "200" ]]; then
    echo "FAIL: $role dashboard summary HTTP $code" >&2
    return 1
  fi
  echo "OK: $role login + me + dashboard (${#pass} char password)"
}

echo "Login UI smoke at $BASE"
curl "${CURL_TLS[@]}" -fsS "$BASE/health" >/dev/null

for role in operator integrator agent admin; do
  login_role "$role" || fail=1
done

html_code="$(curl "${CURL_TLS[@]}" -sS -o /dev/null -w '%{http_code}' "$BASE/")"
if [[ "$html_code" != "200" ]]; then
  echo "FAIL: SPA root HTTP $html_code" >&2
  fail=1
else
  echo "OK: SPA root ($html_code)"
fi

if [[ -f "$CRED_FILE" ]]; then
  echo "Credentials: $CRED_FILE"
else
  echo "WARN: missing $CRED_FILE" >&2
fi

if [[ "$fail" -ne 0 ]]; then
  echo "Login UI smoke FAILED" >&2
  exit 1
fi
echo "Login UI smoke PASS"
