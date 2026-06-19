#!/usr/bin/env bash
# Read-only pytest status — safe for Cursor agents (no attach, no wait).
set -euo pipefail

LOG_GLOB="/tmp/openfdd_pytest_workspace_bridge_*.log"
EXITFILE="/tmp/openfdd_pytest_workspace_bridge.exitcode"
PIDFILE="/tmp/openfdd_pytest_workspace_bridge.pid"

if [[ ! -f "$EXITFILE" ]]; then
  echo "No pytest run found (missing $EXITFILE)"
  exit 2
fi

state="$(cat "$EXITFILE" 2>/dev/null || echo missing)"
pid="?"
[[ -f "$PIDFILE" ]] && pid="$(cat "$PIDFILE")"
running=false
if [[ "$pid" != "?" ]] && [[ -d "/proc/$pid" ]]; then
  running=true
fi

latest_log="$(ls -t $LOG_GLOB 2>/dev/null | head -1 || true)"
echo "state=${state} pid=${pid} running=${running}"
if [[ -n "$latest_log" ]]; then
  echo "log=${latest_log}"
  tail -3 "$latest_log" 2>/dev/null || true
fi

if [[ "$state" == "running" ]]; then
  exit 0
fi
if [[ "$state" =~ ^[0-9]+$ ]]; then
  exit "$state"
fi
exit 3
