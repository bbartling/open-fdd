#!/usr/bin/env bash
# Poll BACnet/Modbus/Haystack driver trees every minute for UI inspection (issue #402).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_auth_lib.sh
source "$ROOT/scripts/openfdd_auth_lib.sh"

BASE="${OPENFDD_API_BASE:-http://127.0.0.1:8080}"
AUTH="$ROOT/workspace/auth.env.local"
INTERVAL="${OPENFDD_DRIVER_POLL_SECONDS:-60}"
KEEP_SNAPSHOTS="${OPENFDD_DRIVER_POLL_KEEP:-120}"
LOG_DIR="${OPENFDD_DRIVER_POLL_DIR:-$ROOT/workspace/logs/driver_poll_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$LOG_DIR"

prune_old_snapshots() {
  local keep="$1"
  mapfile -t old < <(ls -1t "$LOG_DIR"/poll_*_bacnet.json 2>/dev/null | tail -n +"$((keep + 1))" || true)
  for f in "${old[@]}"; do
    local base="${f%_bacnet.json}"
    rm -f "${base}"_*.json 2>/dev/null || true
  done
}

TOKEN="$(openfdd_auth_login_token "$BASE" "$AUTH" integrator)"
echo "Driver poll every ${INTERVAL}s → $LOG_DIR (keep $KEEP_SNAPSHOTS intervals, Ctrl-C to stop)"

while true; do
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  prefix="$LOG_DIR/poll_${ts//:/-}"
  fail=0
  curl -fsS "${BASE}/api/bacnet/driver/tree" -H "Authorization: Bearer $TOKEN" >"${prefix}_bacnet.json" || fail=$((fail + 1))
  curl -fsS "${BASE}/api/bacnet/poll/status" -H "Authorization: Bearer $TOKEN" >"${prefix}_bacnet_poll.json" || fail=$((fail + 1))
  curl -fsS "${BASE}/api/modbus/points" -H "Authorization: Bearer $TOKEN" >"${prefix}_modbus.json" || fail=$((fail + 1))
  curl -fsS "${BASE}/api/haystack/driver/tree" -H "Authorization: Bearer $TOKEN" >"${prefix}_haystack.json" || fail=$((fail + 1))
  curl -fsS "${BASE}/api/haystack/status" -H "Authorization: Bearer $TOKEN" >"${prefix}_haystack_status.json" || fail=$((fail + 1))
  if [[ "$fail" -gt 0 ]]; then
    echo "$ts poll FAILED ($fail/5 requests)" >&2
  else
    echo "$ts poll captured"
  fi
  prune_old_snapshots "$KEEP_SNAPSHOTS"
  sleep "$INTERVAL"
done
