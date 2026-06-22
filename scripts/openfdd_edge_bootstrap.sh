#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

FORCE_AUTH=false
SHOW_SECRETS=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --force-auth) FORCE_AUTH=true ;;
    --show-secrets) SHOW_SECRETS=true ;;
    -h|--help)
      echo "Usage: $0 [--force-auth] [--show-secrets]"
      echo "Creates workspace/auth.env.local (if missing), starts docker compose, validates login."
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

mkdir -p workspace/{auth,reports/rcx,data/rules,data/historian,backups,memory,logs}
AUTH_PATH="$ROOT/workspace/auth.env.local"

auth_init() {
  local args=(auth init --path "$AUTH_PATH")
  $FORCE_AUTH && args+=(--force)
  $SHOW_SECRETS && args+=(--show-secrets)

  if command -v openfdd_edge >/dev/null 2>&1; then
    openfdd_edge "${args[@]}"
  elif [[ -x "$ROOT/edge/target/release/openfdd_edge" ]]; then
    "$ROOT/edge/target/release/openfdd_edge" "${args[@]}"
  else
    (cd "$ROOT/edge" && cargo run --release --bin openfdd_edge -- "${args[@]}")
  fi
}

auth_init

if [[ ! -f "$AUTH_PATH" ]]; then
  echo "auth bootstrap failed: missing $AUTH_PATH" >&2
  exit 1
fi

chmod 600 "$AUTH_PATH" 2>/dev/null || true

if [[ ! -f .env ]]; then
  cat > .env <<EOF
OPENFDD_BIND=0.0.0.0
OPENFDD_EDGE_PROFILE=rust
EOF
fi

echo "Starting containers (auth.env.local is loaded at container creation; recreate after rotating credentials)."
docker compose up -d --build

curl -sf http://127.0.0.1:8080/api/health | jq -e '.ok == true and .auth_required == true'
echo

INTEGRATOR_PW="$(grep '^OFDD_INTEGRATOR_PASSWORD=' "$AUTH_PATH" | cut -d= -f2- | tr -d '\r')"
test -n "$INTEGRATOR_PW"

LOGIN_JSON="$(curl -s -X POST http://127.0.0.1:8080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg u integrator --arg p "$INTEGRATOR_PW" '{username:$u,password:$p}')")"
TOKEN="$(echo "$LOGIN_JSON" | jq -r '.token // .access_token // empty')"
test -n "$TOKEN"
test "$TOKEN" != "null"

curl -sf http://127.0.0.1:8080/api/health/stack -H "Authorization: Bearer $TOKEN" | jq -e '.ok == true'
echo
echo "Bootstrap OK. Dashboard login: integrator + password from workspace/auth.env.local"
