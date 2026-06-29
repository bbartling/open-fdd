#!/usr/bin/env bash
# Start Cursor SDK chat relay for Open-FDD in-app Agent assist (WSL dev).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_bench_lib.sh
source "$ROOT/scripts/openfdd_bench_lib.sh"
openfdd_bench_load_env "$ROOT"

RELAY_DIR="$ROOT/tools/cursor-chat-relay"
LOG_DIR="$ROOT/workspace/logs"
LOG_FILE="$LOG_DIR/cursor-chat-relay.log"
PID_FILE="$ROOT/workspace/agent-chat/cursor-relay.pid"
ENV_FILE="$ROOT/workspace/cursor.env.local"

mkdir -p "$LOG_DIR" "$ROOT/workspace/agent-chat"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

export OPENFDD_REPO_ROOT="$ROOT"
export OFDD_CURSOR_CHAT_PORT="${OFDD_CURSOR_CHAT_PORT:-8787}"
export OFDD_CURSOR_CHAT_HOST="${OFDD_CURSOR_CHAT_HOST:-127.0.0.1}"

if [[ -z "${CURSOR_API_KEY:-}" ]]; then
  echo "ERROR: CURSOR_API_KEY not set." >&2
  echo "  cp workspace/cursor.env.local.example workspace/cursor.env.local" >&2
  echo "  Add your key from https://cursor.com/settings" >&2
  exit 1
fi

if [[ ! -d "$RELAY_DIR/node_modules/@cursor/sdk" ]]; then
  echo "==> Installing cursor-chat-relay dependencies"
  (cd "$RELAY_DIR" && npm install --no-fund --no-audit)
fi

if [[ -f "$PID_FILE" ]]; then
  old_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
    echo "Cursor relay already running (pid $old_pid) — http://127.0.0.1:${OFDD_CURSOR_CHAT_PORT}"
    exit 0
  fi
fi

echo "==> Starting Cursor chat relay on http://127.0.0.1:${OFDD_CURSOR_CHAT_PORT}"
nohup env OPENFDD_REPO_ROOT="$ROOT" OFDD_CURSOR_CHAT_PORT="$OFDD_CURSOR_CHAT_PORT" \
  CURSOR_API_KEY="$CURSOR_API_KEY" OFDD_CURSOR_AGENT_MODEL="${OFDD_CURSOR_AGENT_MODEL:-composer-2.5}" \
  node "$RELAY_DIR/server.mjs" >>"$LOG_FILE" 2>&1 &
echo $! >"$PID_FILE"
sleep 1

if curl -fsS --max-time 3 "http://127.0.0.1:${OFDD_CURSOR_CHAT_PORT}/health" | jq -e '.ok' >/dev/null; then
  echo "OK: Cursor relay healthy — log: workspace/logs/cursor-chat-relay.log"
else
  echo "WARN: relay started but health check failed — see $LOG_FILE" >&2
  tail -20 "$LOG_FILE" >&2 || true
  exit 1
fi
