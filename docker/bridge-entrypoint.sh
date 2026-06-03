#!/usr/bin/env bash
# Ensure bind-mounted workspace/data is writable by the bridge process (avoid root-owned model.json).
set -euo pipefail
WS="${OPENFDD_WORKSPACE_DIR:-/var/openfdd/workspace}"
if [[ -d "$WS" ]]; then
  owner="$(stat -c '%u:%g' "$WS" 2>/dev/null || echo '1000:1000')"
  chown -R "$owner" "$WS/data" "$WS/bacnet" 2>/dev/null || true
  chmod -R u+rwX "$WS/data" "$WS/bacnet" 2>/dev/null || true
fi
exec uvicorn openfdd_bridge.main:app --host 0.0.0.0 --port "${OFDD_BRIDGE_PORT:-8765}"
