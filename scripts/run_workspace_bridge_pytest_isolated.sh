#!/usr/bin/env bash
# Run tests/workspace_bridge pytest in a systemd user unit (not attached to Cursor).
#
# Agents: poll only — never run `pytest tests/workspace_bridge` directly in chat.
#   ./scripts/run_workspace_bridge_pytest_isolated.sh
#   ./scripts/workspace_bridge_pytest_status.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

LOG="/tmp/openfdd_pytest_workspace_bridge_$(date -u +%Y%m%d_%H%M%S).log"
EXITFILE="/tmp/openfdd_pytest_workspace_bridge.exitcode"
PIDFILE="/tmp/openfdd_pytest_workspace_bridge.pid"
UNIT="openfdd-pytest-workspace-bridge"

export OPENFDD_REPO_ROOT="$ROOT"
export OFDD_DESKTOP_DATA_DIR="${OFDD_DESKTOP_DATA_DIR:-$ROOT/workspace/data}"
export PYTHONPATH="${PYTHONPATH:-$ROOT:$ROOT/workspace/api}"

chmod +x "${ROOT}/scripts/workspace_bridge_pytest_worker.sh"
echo "running" >"$EXITFILE"

if command -v systemd-run >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
  systemd-run --user \
    --unit="$UNIT" \
    --description="Open-FDD workspace_bridge pytest" \
    --working-directory="$ROOT" \
    --property=KillMode=control-group \
    --property=CollectMode=inactive \
    --setenv=OPENFDD_REPO_ROOT="$ROOT" \
    --setenv=OFDD_DESKTOP_DATA_DIR="$OFDD_DESKTOP_DATA_DIR" \
    --setenv=PYTHONPATH="$PYTHONPATH" \
    --property=StandardOutput=append:"$LOG" \
    --property=StandardError=append:"$LOG" \
    "${ROOT}/scripts/workspace_bridge_pytest_worker.sh" "$LOG" "$EXITFILE" >/dev/null
  sleep 1
  pgrep -f "pytest tests/workspace_bridge" | head -1 >"$PIDFILE" || true
  LAUNCHER="systemd-run --user"
else
  setsid "${ROOT}/scripts/workspace_bridge_pytest_worker.sh" "$LOG" "$EXITFILE" &
  echo $! >"$PIDFILE"
  LAUNCHER="setsid"
fi

cat <<EOF
==> Isolated workspace_bridge pytest launched (${LAUNCHER})
    log:      ${LOG}
    exitfile: ${EXITFILE}
    poll:     ./scripts/workspace_bridge_pytest_status.sh
    DO NOT wait from Cursor — read exitfile when status shows done.
EOF
