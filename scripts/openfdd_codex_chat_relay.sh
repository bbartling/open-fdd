#!/usr/bin/env bash
# Start Codex CLI chat relay for in-app Agent assist (WSL dev).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RELAY_DIR="$ROOT/tools/codex-chat-relay"
LOG_DIR="$ROOT/workspace/logs"
LOG_FILE="$LOG_DIR/codex-chat-relay.log"
PID_FILE="$ROOT/workspace/agent-chat/codex-relay.pid"
ENV_FILE="$ROOT/workspace/codex.env.local"

mkdir -p "$LOG_DIR" "$ROOT/workspace/agent-chat" "$ROOT/workspace/agent-toolshed"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

export OPENFDD_REPO_ROOT="$ROOT"
export OFDD_CODEX_CHAT_PORT="${OFDD_CODEX_CHAT_PORT:-8788}"
export OFDD_CODEX_CHAT_HOST="${OFDD_CODEX_CHAT_HOST:-127.0.0.1}"

if ! command -v codex >/dev/null 2>&1; then
  echo "ERROR: codex CLI not found — npm i -g @openai/codex" >&2
  exit 1
fi

if [[ -f "$PID_FILE" ]]; then
  old_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
    echo "Codex relay already running (pid $old_pid) — http://127.0.0.1:${OFDD_CODEX_CHAT_PORT}"
    exit 0
  fi
fi

echo "==> Starting Codex chat relay on http://127.0.0.1:${OFDD_CODEX_CHAT_PORT}"
nohup env OPENFDD_REPO_ROOT="$ROOT" OFDD_CODEX_CHAT_PORT="$OFDD_CODEX_CHAT_PORT" \
  OFDD_CODEX_AGENT_MODEL="${OFDD_CODEX_AGENT_MODEL:-gpt-5.4-mini}" \
  node "$RELAY_DIR/server.mjs" >>"$LOG_FILE" 2>&1 &
echo $! >"$PID_FILE"
sleep 1

if curl -fsS --max-time 5 "http://127.0.0.1:${OFDD_CODEX_CHAT_PORT}/health" | jq -e '.ok' >/dev/null; then
  echo "OK: Codex relay healthy — log: workspace/logs/codex-chat-relay.log"
  curl -fsS "http://127.0.0.1:${OFDD_CODEX_CHAT_PORT}/health" | jq -c '{ok,codex_logged_in,openfdd_mcp_configured}'
else
  echo "WARN: relay started but health failed — see $LOG_FILE" >&2
  tail -20 "$LOG_FILE" >&2 || true
  exit 1
fi
