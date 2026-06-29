#!/usr/bin/env bash
# One-time / refresh: Codex MCP + JWT + in-app chat relay (WSL dev — not in GHCR).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_bench_lib.sh
source "$ROOT/scripts/openfdd_bench_lib.sh"
openfdd_bench_load_env "$ROOT"

chmod +x "$ROOT/scripts/openfdd_mcp_stdio.sh"

echo "==> Kill stale agent chat relays"
pkill -f "tools/cursor-chat-relay/server.mjs" 2>/dev/null || true
pkill -f "tools/codex-chat-relay/server.mjs" 2>/dev/null || true
rm -f "$ROOT/workspace/agent-chat/cursor-relay.pid" "$ROOT/workspace/agent-chat/codex-relay.pid" 2>/dev/null || true

echo "==> Ensure openfdd-mcp binary"
if [[ ! -x "$ROOT/target/release/openfdd-mcp" ]]; then
  (cd "$ROOT" && cargo build --release -p openfdd-mcp)
fi

echo "==> Edge health"
if ! curl -fsS --max-time 3 http://127.0.0.1:8080/api/health >/dev/null 2>&1; then
  echo "WARN: bridge not on :8080 — start edge before MCP chat" >&2
fi

echo "==> Register openfdd MCP with Codex (project config + CLI)"
if ! codex mcp list 2>/dev/null | rg -q '^openfdd\b'; then
  codex mcp add openfdd -- "$ROOT/scripts/openfdd_mcp_stdio.sh" || true
fi

echo "==> Codex login check"
if ! codex mcp list >/dev/null 2>&1; then
  echo "WARN: codex CLI error — run: codex login" >&2
fi

mkdir -p "$ROOT/workspace/agent-toolshed" "$ROOT/workspace/agent-chat"
echo "OK: toolshed at workspace/agent-toolshed/ (gitignored)"

"$ROOT/scripts/openfdd_codex_chat_relay.sh"
