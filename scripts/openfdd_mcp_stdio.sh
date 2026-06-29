#!/usr/bin/env bash
# Stdio MCP launcher for Codex/Cursor — refreshes integrator JWT when needed.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_auth_lib.sh
source "$ROOT/scripts/openfdd_auth_lib.sh"

export OPENFDD_API_BASE="${OPENFDD_API_BASE:-http://127.0.0.1:8080}"
export OPENFDD_COMMISSION_BASE="${OPENFDD_COMMISSION_BASE:-http://127.0.0.1:9091}"

MCP_BIN="${OPENFDD_MCP_BIN:-$ROOT/target/release/openfdd-mcp}"
if [[ ! -x "$MCP_BIN" ]]; then
  MCP_BIN="$ROOT/target/debug/openfdd-mcp"
fi
if [[ ! -x "$MCP_BIN" ]]; then
  echo "openfdd-mcp binary not found — run: cargo build --release -p openfdd-mcp" >&2
  exit 1
fi

if [[ -z "${OPENFDD_MCP_TOKEN:-}" ]]; then
  AUTH_FILE="$ROOT/workspace/auth.env.local"
  if [[ ! -f "$AUTH_FILE" ]]; then
    echo "workspace/auth.env.local missing — cannot obtain JWT" >&2
    exit 1
  fi
  PW="$(openfdd_auth_plaintext_password "$AUTH_FILE" integrator)"
  OPENFDD_MCP_TOKEN="$(
    curl -sf -X POST "${OPENFDD_API_BASE}/api/auth/login" \
      -H 'Content-Type: application/json' \
      -d "$(jq -nc --arg u integrator --arg p "$PW" '{username:$u,password:$p}')" \
    | jq -r '.token // .access_token // empty'
  )"
  if [[ -z "$OPENFDD_MCP_TOKEN" ]]; then
    echo "JWT login failed — check integrator password" >&2
    exit 1
  fi
  export OPENFDD_MCP_TOKEN
fi

exec "$MCP_BIN"
