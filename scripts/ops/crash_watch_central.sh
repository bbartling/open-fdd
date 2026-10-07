#!/usr/bin/env bash
# Poll /api/health started_at; on flip, capture Railway central logs into ART (Q1a).
# Usage:
#   OPENFDD_API_BASE=https://… ARTIFACT_DIR=reports/… ./scripts/ops/crash_watch_central.sh
# Optional: INTERVAL_SECS=20, OPENFDD_RAILWAY_CENTRAL_SERVICE=…
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BASE="${OPENFDD_API_BASE:-${RAILWAY_BASE:-}}"
ART="${ARTIFACT_DIR:-$ROOT/reports/crash_watch}"
INTERVAL="${INTERVAL_SECS:-20}"
LOG="$ART/crash_watch.log"
FLAG="$ART/crash_watch_RESTART.flag"

if [[ -z "$BASE" ]]; then
  echo "FAIL: set OPENFDD_API_BASE or RAILWAY_BASE" >&2
  exit 2
fi
mkdir -p "$ART"
: >"$LOG"

echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) crash_watch start base=${BASE%/}" | tee -a "$LOG"
prev=""
while true; do
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  body="$(curl -fsS --max-time 8 "${BASE%/}/api/health" 2>/dev/null || true)"
  started="$(python3 -c 'import json,sys; d=json.loads(sys.argv[1] or "{}"); print(d.get("started_at") or "")' "$body" 2>/dev/null || true)"
  version="$(python3 -c 'import json,sys; d=json.loads(sys.argv[1] or "{}"); print(d.get("version") or "")' "$body" 2>/dev/null || true)"
  uptime="$(python3 -c 'import json,sys; d=json.loads(sys.argv[1] or "{}"); print(d.get("uptime_secs") if d.get("uptime_secs") is not None else "")' "$body" 2>/dev/null || true)"
  if [[ -z "$started" ]]; then
    echo "$ts ok started_at=? version= uptime=" | tee -a "$LOG"
  elif [[ -z "$prev" ]]; then
    prev="$started"
    echo "$ts baseline started_at=$started" | tee -a "$LOG"
    echo "$ts ok started_at=$started version=$version uptime=$uptime" | tee -a "$LOG"
  elif [[ "$started" != "$prev" ]]; then
    echo "$ts RESTART detected old=$prev new=$started version=$version" | tee -a "$LOG"
    echo "$started" >"$FLAG"
    ARTIFACT_DIR="$ART" FLIP_UTC="$started" \
      bash "$ROOT/scripts/ops/capture_railway_central_logs.sh" | tee -a "$LOG" || true
    prev="$started"
  else
    echo "$ts ok started_at=$started version=$version uptime=$uptime" | tee -a "$LOG"
  fi
  sleep "$INTERVAL"
done
