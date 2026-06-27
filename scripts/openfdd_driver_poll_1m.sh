#!/usr/bin/env bash
# Poll BACnet/Modbus/Haystack driver trees every minute for UI inspection (issue #402).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_auth_lib.sh
source "$ROOT/scripts/openfdd_auth_lib.sh"

BASE="${OPENFDD_API_BASE:-http://127.0.0.1:8080}"
AUTH="$ROOT/workspace/auth.env.local"
INTERVAL="${OPENFDD_DRIVER_POLL_SECONDS:-60}"
LOG_DIR="${OPENFDD_DRIVER_POLL_DIR:-$ROOT/workspace/logs/driver_poll_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$LOG_DIR"

TOKEN="$(openfdd_auth_login_token "$BASE" "$AUTH" integrator)"
echo "Driver poll every ${INTERVAL}s → $LOG_DIR (Ctrl-C to stop)"

while true; do
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  prefix="$LOG_DIR/poll_${ts//:/-}"
  curl -fsS "${BASE}/api/bacnet/driver/tree" -H "Authorization: Bearer $TOKEN" >"${prefix}_bacnet.json" || true
  curl -fsS "${BASE}/api/bacnet/poll/status" -H "Authorization: Bearer $TOKEN" >"${prefix}_bacnet_poll.json" || true
  curl -fsS "${BASE}/api/modbus/points" -H "Authorization: Bearer $TOKEN" >"${prefix}_modbus.json" || true
  curl -fsS "${BASE}/api/haystack/driver/tree" -H "Authorization: Bearer $TOKEN" >"${prefix}_haystack.json" || true
  curl -fsS "${BASE}/api/haystack/status" -H "Authorization: Bearer $TOKEN" >"${prefix}_haystack_status.json" || true
  echo "$ts poll captured"
  sleep "$INTERVAL"
done
