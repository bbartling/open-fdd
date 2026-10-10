#!/usr/bin/env bash
# Poll /api/health started_at; on flip, capture Railway central logs + events +
# memory metrics into ART (Q1a / #1179). Soft-OPEN 370 T3b honesty:
#   - query service events (not deployments)
#   - continuous pre-flip memory_budget series in the poll log
#   - never bait greps with platform event type strings in notes
#   - empty events feed = unavailable/unknown, not proof of clean survival
# Usage:
#   OPENFDD_API_BASE=https://… ARTIFACT_DIR=reports/… ./scripts/ops/crash_watch_central.sh
# Optional: INTERVAL_SECS=20, OPENFDD_RAILWAY_CENTRAL_SERVICE=…
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BASE="${OPENFDD_API_BASE:-${RAILWAY_BASE:-${CENTRAL_BASE:-${BASE:-}}}}"
ART="${ARTIFACT_DIR:-$ROOT/reports/crash_watch}"
INTERVAL="${INTERVAL_SECS:-20}"
LOG="$ART/crash_watch.log"
SERIES="$ART/memory_series.jsonl"
FLAG="$ART/crash_watch_RESTART.flag"
SERVICE="${OPENFDD_RAILWAY_CENTRAL_SERVICE:-openfdd-central-cQ-F}"

if [[ -z "$BASE" ]]; then
  echo "FAIL: set OPENFDD_API_BASE or RAILWAY_BASE" >&2
  exit 2
fi
mkdir -p "$ART"
: >"$LOG"
: >"$SERIES"

snapshot_events_and_metrics() {
  local flip="$1"
  local stamp
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  local events_out="$ART/railway_events_flip_${stamp}.json"
  local metrics_out="$ART/railway_metrics_flip_${stamp}.json"

  if command -v railway >/dev/null 2>&1; then
    # Best-effort platform events. Never invent crash causes.
    # Note text deliberately avoids the platform event token so a grep of this
    # file cannot false-positive (M70-10).
    {
      echo "{"
      echo "  \"captured_at_utc\": \"$stamp\","
      echo "  \"flip_started_at\": \"$flip\","
      echo "  \"service\": \"$SERVICE\","
      echo "  \"note\": \"parse edges for platform event types; empty/error body means evidence unavailable\","
      echo "  \"query\": \"events\","
      echo "  \"raw\": "
      if railway api --help >/dev/null 2>&1; then
        # Prefer service-filtered events. Deployments are NOT crash evidence.
        railway api "query { events(first: 20) { edges { node { id type createdAt message } } } }" 2>/dev/null \
          || echo '{"error":"railway api events query unavailable","evidence":"unavailable"}'
      else
        echo '{"error":"railway api subcommand unavailable","evidence":"unavailable"}'
      fi
      echo "}"
    } >"$events_out" 2>/dev/null || echo "{\"error\":\"events capture failed\",\"flip\":\"$flip\",\"evidence\":\"unavailable\"}" >"$events_out"

    python3 -c "
import json, urllib.request, os, sys
base = os.environ.get('OPENFDD_API_BASE') or os.environ.get('RAILWAY_BASE') or ''
out = sys.argv[1]
flip = sys.argv[2]
stamp = sys.argv[3]
series_path = sys.argv[4]
payload = {
    'captured_at_utc': stamp,
    'flip_started_at': flip,
    'health': None,
    'pre_flip_memory_series_tail': [],
    'note': 'pair with continuous memory_series.jsonl + central logs +/- 2 min',
}
try:
    req = urllib.request.Request(base.rstrip('/') + '/api/health', headers={'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=8) as resp:
        payload['health'] = json.loads(resp.read().decode() or '{}')
except Exception as exc:
    payload['error'] = str(exc)
try:
    lines = open(series_path, encoding='utf-8').read().splitlines()
    payload['pre_flip_memory_series_tail'] = [json.loads(x) for x in lines[-30:]]
except Exception:
    payload['pre_flip_memory_series_tail'] = []
open(out, 'w', encoding='utf-8').write(json.dumps(payload, indent=2) + '\n')
print('wrote', out)
" "$metrics_out" "$flip" "$stamp" "$SERIES" || true

    # Parse structured event types only — never grep explanatory notes.
    python3 - <<PY | tee -a "$LOG"
import json, sys
path = "$events_out"
stamp = "$stamp"
try:
    doc = json.load(open(path, encoding="utf-8"))
except Exception as exc:
    print(f"{stamp} events_parse=unavailable err={exc}")
    sys.exit(0)
raw = doc.get("raw") if isinstance(doc, dict) else None
if isinstance(raw, str):
    try:
        raw = json.loads(raw)
    except Exception:
        raw = None
if not isinstance(raw, dict) or raw.get("error"):
    print(f"{stamp} events_evidence=unavailable")
    sys.exit(0)
edges = (((raw.get("data") or {}).get("events") or {}).get("edges")) or raw.get("edges") or []
types = []
for e in edges:
    node = (e or {}).get("node") or e or {}
    t = str(node.get("type") or "")
    if t:
        types.append(t)
# Platform may use distinct enum strings; report presence without inventing cause.
interesting = [t for t in types if any(x in t.lower() for x in ("oom", "crash", "kill", "rebooted"))]
if interesting:
    print(f"{stamp} HINT: platform event types={interesting} — cite with metrics+logs (not note text)")
else:
    print(f"{stamp} events_evidence=present types={types[:8]}")
PY
  else
    echo "{\"error\":\"railway CLI missing\",\"flip\":\"$flip\",\"evidence\":\"unavailable\"}" >"$events_out"
    echo "{\"error\":\"railway CLI missing\",\"flip\":\"$flip\",\"evidence\":\"unavailable\"}" >"$metrics_out"
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
  # Continuous memory series (pre-flip evidence).
  python3 -c '
import json,sys,os
body=sys.argv[1] or "{}"
ts=sys.argv[2]
path=sys.argv[3]
try:
    d=json.loads(body)
except Exception:
    d={}
mb=d.get("memory_budget") or {}
row={"ts":ts,"started_at":d.get("started_at"),"version":d.get("version"),
     "sample_ms":mb.get("sample_ms"),"source":mb.get("source"),
     "shed_state":mb.get("shed_state"),"current_bytes":mb.get("current_bytes"),
     "peak_bytes":mb.get("peak_bytes"),"last_trip":mb.get("last_trip")}
with open(path,"a",encoding="utf-8") as f:
    f.write(json.dumps(row)+"\n")
' "$body" "$ts" "$SERIES" 2>/dev/null || true

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
