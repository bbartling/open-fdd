#!/usr/bin/env bash
# Reset in-app agent chat: stop relays, clear session scratch files.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

pkill -f "tools/cursor-chat-relay/server.mjs" 2>/dev/null || true
pkill -f "tools/codex-chat-relay/server.mjs" 2>/dev/null || true
pkill -f "codex exec" 2>/dev/null || true

rm -f "$ROOT/workspace/agent-chat/cursor-relay.pid" \
  "$ROOT/workspace/agent-chat/codex-relay.pid" \
  "$ROOT/workspace/agent-chat/codex-session-id.txt" \
  "$ROOT/workspace/agent-chat/cursor-agent-id.txt" 2>/dev/null || true
rm -f "$ROOT/workspace/agent-chat/codex-out-"*.txt 2>/dev/null || true

curl -fsS -X POST "http://127.0.0.1:${OFDD_CODEX_CHAT_PORT:-8788}/reset" >/dev/null 2>&1 || true

echo "OK: agent chat relays stopped, session scratch cleared"
