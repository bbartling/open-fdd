#!/usr/bin/env bash
# Poll half-hour smoke until finished — safe background watcher (not for Cursor attach).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG="/tmp/smoke_half_hour_poll.log"
: >"$LOG"
while true; do
  if "${ROOT}/scripts/smoke_bench_5007_half_hour_status.sh" >>"$LOG" 2>&1; then
    echo "SMOKE_DONE pass $(date -u +%Y-%m-%dT%H:%M:%SZ)" >>"$LOG"
    exit 0
  fi
  if [[ "$ec" -eq 1 ]]; then
    echo "SMOKE_DONE fail $(date -u +%Y-%m-%dT%H:%M:%SZ)" >>"$LOG"
    exit 1
  fi
  if [[ "$ec" -eq 2 ]]; then
    echo "poll $(date -u +%H:%M:%S) still running" >>"$LOG"
    sleep 120
    continue
  fi
  echo "poll $(date -u +%H:%M:%S) unexpected exit $ec" >>"$LOG"
  sleep 120
done
