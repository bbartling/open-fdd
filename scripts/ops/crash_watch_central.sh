#!/usr/bin/env bash
# Poll /api/health started_at; on flip, capture Railway central logs + events +
# memory metrics into ART (Q1a / #1179).
# Usage:
#   OPENFDD_API_BASE=https://… ARTIFACT_DIR=reports/… ./scripts/ops/crash_watch_central.sh
# Optional: INTERVAL_SECS=20, OPENFDD_RAILWAY_CENTRAL_SERVICE=…
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BASE="${OPENFDD_API_BASE:-${RAILWAY_BASE:-${CENTRAL_BASE:-${BASE:-}}}}"
ART="${ARTIFACT_DIR:-$ROOT/reports/crash_watch}"
INTERVAL="${INTERVAL_SECS:-20}"
LOG="$ART/crash_watch.log"
FLAG="$ART/crash_watch_RESTART.flag"
SERVICE="${OPENFDD_RAILWAY_CENTRAL_SERVICE:-openfdd-central-cQ-F}"

if [[ -z "$BASE" ]]; then
  echo "FAIL: set OPENFDD_API_BASE or RAILWAY_BASE" >&2
  exit 2
fi
mkdir -p "$ART"
: >"$LOG"

snapshot_events_and_metrics() {
  local flip="$1"
  local stamp
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  local events_out="$ART/railway_events_flip_${stamp}.json"
  local metrics_out="$ART/railway_metrics_flip_${stamp}.json"

  if command -v railway >/dev/null 2>&1; then
    # Best-effort platform events (oom_killed / crashed). Never invent OOM.
    {
      echo "{"
      echo "  \"captured_at_utc\": \"$stamp\","
      echo "  \"flip_started_at\": \"$flip\","
      echo "  \"service\": \"$SERVICE\","
      echo "  \"note\": \"filter locally for oom_killed/crashed; empty body is incomplete evidence\","
      echo "  \"raw\": "
      railway logs -s "$SERVICE" -n 5 2>/dev/null | head -c 1 >/dev/null || true
      # Prefer GraphQL events when railway api is available.
      if railway api --help >/dev/null 2>&1; then
        railway api 'query { deployments(first: 5) { edges { node { id status } } } }' 2>/dev/null \
          || echo '{"error":"railway api events query unavailable"}'
      else
        echo '{"error":"railway api subcommand unavailable — attach events manually"}'
      fi
      echo "}"
    } >"$events_out" 2>/dev/null || echo "{\"error\":\"events capture failed\",\"flip\":\"$flip\"}" >"$events_out"

    # Memory series snapshot via health memory_budget when present + cgroup hint.
    python3 -c "
import json, urllib.request, os, sys
base = os.environ.get('OPENFDD_API_BASE') or os.environ.get('RAILWAY_BASE') or ''
out = sys.argv[1]
flip = sys.argv[2]
stamp = sys.argv[3]
payload = {'captured_at_utc': stamp, 'flip_started_at': flip, 'health': None, 'note': 'prefer Railway metrics UI series + health.memory_budget'}
try:
    req = urllib.request.Request(base.rstrip('/') + '/api/health', headers={'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=8) as resp:
        payload['health'] = json.loads(resp.read().decode() or '{}')
except Exception as exc:
    payload['error'] = str(exc)
open(out, 'w', encoding='utf-8').write(json.dumps(payload, indent=2) + '\n')
print('wrote', out)
" "$metrics_out" "$flip" "$stamp" || true
    if grep -Eiq 'oom_killed' "$events_out" 2>/dev/null; then
      echo "$stamp HINT: oom_killed present in events capture — cite with metrics+logs" | tee -a "$LOG"
    fi
  else
    echo "{\"error\":\"railway CLI missing\",\"flip\":\"$flip\"}" >"$events_out"
    echo "{\"error\":\"railway CLI missing\",\"flip\":\"$flip\"}" >"$metrics_out"
  fi
}

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
    OPENFDD_API_BASE="$BASE" ARTIFACT_DIR="$ART" FLIP_UTC="$started" \
      bash "$ROOT/scripts/ops/capture_railway_central_logs.sh" | tee -a "$LOG" || true
    OPENFDD_API_BASE="$BASE" snapshot_events_and_metrics "$started" || true
    prev="$started"
  else
    echo "$ts ok started_at=$started version=$version uptime=$uptime" | tee -a "$LOG"
  fi
  sleep "$INTERVAL"
done
