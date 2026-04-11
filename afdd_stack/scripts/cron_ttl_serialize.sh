#!/usr/bin/env bash
# Trigger Open-FDD data-model TTL sync from cron or systemd timer.
#
# Requires: curl, API reachable from this host (same Docker network, localhost, or VPN).
#
# Environment:
#   OFDD_API_BASE   Base URL (default http://127.0.0.1:8000)
#   OFDD_CRON_SYNC_MODE
#       serialize — POST /data-model/serialize (fast; in-memory graph → file)
#       reset     — POST /data-model/reset (Brick from DB only; drops BACnet triples in graph)
#   OFDD_ACCESS_TOKEN  If app user auth is enabled, pass Bearer token (otherwise omit).
#
# Crontab examples (run as user that can reach the API):
#   */15 * * * * OFDD_API_BASE=http://api:8000 /path/to/cron_ttl_serialize.sh >>/var/log/ofdd_ttl_sync.log 2>&1
#   5 * * * * OFDD_CRON_SYNC_MODE=reset OFDD_API_BASE=http://127.0.0.1:8000 /path/to/cron_ttl_serialize.sh
#
set -euo pipefail

BASE="${OFDD_API_BASE:-http://127.0.0.1:8000}"
MODE="${OFDD_CRON_SYNC_MODE:-serialize}"
TOKEN="${OFDD_ACCESS_TOKEN:-}"

curl_args=(-fsS -X POST "${BASE}/data-model/${MODE}" -H "Content-Type: application/json")
if [[ -n "${TOKEN}" ]]; then
  curl_args+=(-H "Authorization: Bearer ${TOKEN}")
fi

case "${MODE}" in
  serialize | reset) ;;
  *)
    echo "OFDD_CRON_SYNC_MODE must be 'serialize' or 'reset', got: ${MODE}" >&2
    exit 2
    ;;
esac

echo "$(date -Iseconds) ${MODE} ${BASE}/data-model/${MODE}"
curl "${curl_args[@]}"
echo
