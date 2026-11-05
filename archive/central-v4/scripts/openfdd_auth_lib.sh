#!/usr/bin/env bash
# Resolve plaintext password for an auth role from bootstrap handoff or env.
# auth.env.local stores bcrypt hashes only — never use OFDD_*_PASSWORD_HASH as password.
#
# Usage: openfdd_auth_plaintext_password <auth.env.local path> <role>
# Env override: OPENFDD_INTEGRATOR_PASSWORD, OPENFDD_AGENT_PASSWORD, OPENFDD_OPERATOR_PASSWORD
openfdd_auth_plaintext_password() {
  local auth_file="${1:?auth file}"
  local role="${2:?role}"
  local role_upper env_key pw handoff ws

  role_upper="$(printf '%s' "$role" | tr '[:lower:]' '[:upper:]')"
  env_key="OPENFDD_${role_upper}_PASSWORD"
  if [[ -n "${!env_key:-}" ]]; then
    printf '%s' "${!env_key}"
    return 0
  fi

  ws="$(dirname "$auth_file")"
  handoff="$ws/bootstrap_credentials.once.txt"
  if [[ -f "$handoff" ]]; then
    pw="$(grep -E "^${role}:" "$handoff" | head -1 | cut -d: -f2- | sed 's/^ //' || true)"
    if [[ -n "$pw" && "$pw" != \$2b\$* ]]; then
      printf '%s' "$pw"
      return 0
    fi
  fi

  local plain_key="OFDD_${role_upper}_PASSWORD"
  if [[ -f "$auth_file" ]]; then
    pw="$(grep "^${plain_key}=" "$auth_file" | cut -d= -f2- | tr -d '\r' || true)"
    if [[ -n "$pw" && "$pw" != \$2b\$* ]]; then
      printf '%s' "$pw"
      return 0
    fi
  fi

  echo "ERROR: no plaintext password for role '$role'. Run:" >&2
  echo "  ./scripts/openfdd_auth_init.sh --rotate --all --show-secrets --restart" >&2
  echo "Or set ${env_key} or create $handoff" >&2
  return 1
}

openfdd_auth_login_token() {
  local base="${1:?base url}"
  local auth_file="${2:?auth file}"
  local role="${3:-integrator}"
  local user pw
  local CURL_TLS=()
  if [[ "$base" == https://* ]]; then CURL_TLS=(-k); fi
  user="$(grep "^OFDD_${role^^}_USER=" "$auth_file" | cut -d= -f2- | tr -d '\r' || true)"
  user="${user:-$role}"
  pw="$(openfdd_auth_plaintext_password "$auth_file" "$role")" || return 1
  curl "${CURL_TLS[@]}" -fsS -X POST "${base}/api/auth/login" \
    -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg u "$user" --arg p "$pw" '{username:$u,password:$p}')" \
    | jq -r '.token // .access_token // empty'
}
