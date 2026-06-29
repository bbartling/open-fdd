#!/usr/bin/env bash
# Safe bench restart: recreate stack without volume prune; optional BACnet poll daemon.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_rust_site_lib.sh
source "$ROOT/scripts/openfdd_rust_site_lib.sh"

COMPOSE="$(openfdd_rust_resolve_compose_file "$ROOT")"
[[ -n "$COMPOSE" && -f "$COMPOSE" ]] || {
  echo "ERROR: compose file not found under $ROOT" >&2
  exit 1
}

echo "==> Bench safe restart (no down -v)"
docker compose -f "$COMPOSE" up -d --remove-orphans

deadline=$((SECONDS + ${OPENFDD_HEALTH_TIMEOUT_SECS:-90}))
until curl -fsS "${OPENFDD_API_BASE:-http://127.0.0.1:8080}/api/health" >/dev/null 2>&1; do
  if (( SECONDS >= deadline )); then
    echo "ERROR: bridge not healthy after ${OPENFDD_HEALTH_TIMEOUT_SECS:-90}s" >&2
    exit 1
  fi
  sleep 2
done
echo "OK: bridge healthy"

if [[ -x "$ROOT/scripts/openfdd_bacnet_poll_daemon.sh" ]]; then
  "$ROOT/scripts/openfdd_bacnet_poll_daemon.sh" start 2>/dev/null || true
fi
