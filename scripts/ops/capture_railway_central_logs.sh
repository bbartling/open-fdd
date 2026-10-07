#!/usr/bin/env bash
# Capture Railway openfdd-central logs around a started_at flip for Soft-OPEN RCA.
# Usage:
#   ARTIFACT_DIR=... FLIP_UTC=2026-10-07T13:09:08Z \
#     ./scripts/ops/capture_railway_central_logs.sh
#
# Writes: $ARTIFACT_DIR/railway_central_crash_<UTC>.log (secrets redacted lightly).
# Does NOT claim OOM. Restart without this attachment = incomplete evidence (Q1a).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ART="${ARTIFACT_DIR:-$ROOT/reports/crash_capture}"
FLIP_UTC="${FLIP_UTC:-}"
WINDOW_MIN="${OPENFDD_CRASH_LOG_WINDOW_MIN:-3}"
SERVICE="${OPENFDD_RAILWAY_CENTRAL_SERVICE:-openfdd-central-cQ-F}"
LINES="${OPENFDD_RAILWAY_LOG_LINES:-800}"

mkdir -p "$ART"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
out="$ART/railway_central_crash_${stamp}.log"

if ! command -v railway >/dev/null 2>&1; then
  echo "BLOCKED: railway CLI not on PATH" | tee "$out"
  exit 2
fi

{
  echo "# railway central crash capture"
  echo "# captured_at_utc=$stamp"
  echo "# flip_started_at=${FLIP_UTC:-unset}"
  echo "# window_min=$WINDOW_MIN service=$SERVICE"
  echo "# note: death reason may be in the minutes BEFORE flip; attach full slice"
  echo
  # Prefer since/until when FLIP_UTC is an RFC3339 instant.
  if [[ -n "$FLIP_UTC" ]]; then
    # Portable ± window via python (date -d GNU-only).
    read -r since until < <(python3 - <<PY
from datetime import datetime, timedelta, timezone
raw = "${FLIP_UTC}".replace("Z", "+00:00")
flip = datetime.fromisoformat(raw)
if flip.tzinfo is None:
    flip = flip.replace(tzinfo=timezone.utc)
w = timedelta(minutes=int("${WINDOW_MIN}"))
print((flip - w).strftime("%Y-%m-%dT%H:%M:%SZ"), (flip + w).strftime("%Y-%m-%dT%H:%M:%SZ"))
PY
)
    echo "# since=$since until=$until"
    railway logs -s "$SERVICE" -n "$LINES" --since "$since" --until "$until" 2>&1 \
      || railway logs -s "$SERVICE" -n "$LINES" 2>&1 \
      || true
  else
    railway logs -s "$SERVICE" -n "$LINES" 2>&1 || true
  fi
} | python3 - <<'PY' | tee "$out"
import re, sys
text = sys.stdin.read()
# Light redact: bearer tokens / password= values. Keep panic/ERROR/WARN.
text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+", r"\1[REDACTED]", text)
text = re.sub(r'(?i)("password"\s*:\s*")[^"]*"', r'\1[REDACTED]"', text)
text = re.sub(r"(?i)(password=)\S+", r"\1[REDACTED]", text)
sys.stdout.write(text)
PY

echo "wrote $out"
# Quick triage hints (not a verdict).
if grep -Eiq 'oom|out of memory|Killed process' "$out"; then
  echo "HINT: OOM-like strings present — cite them; do not invent OOM without this"
elif grep -Eiq 'FATAL openfdd-central panic|panic at' "$out"; then
  echo "HINT: panic/FATAL line present — attach this file to #1127/#1169"
else
  echo "HINT: no OOM/panic string in slice — death reason may still be missing; widen window"
fi
