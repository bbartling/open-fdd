#!/usr/bin/env bash
# Only fieldbus compose stacks may reference BACnet UDP :47808; central must not publish it.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

echo "== gate: sole_bacnet_udp_owner =="

CENTRAL_COMPOSE=(
  docker/compose.central.yml
  docker/compose.standalone.yml
)

FIELDBUS_COMPOSE=(
  docker/compose.edge.yml
  docker/compose.standalone.yml
)

failed=0

for f in "${CENTRAL_COMPOSE[@]}"; do
  if [[ ! -f "$f" ]]; then
    echo "FAIL: missing $f" >&2
    failed=1
    continue
  fi
  if rg -n '47808' "$f" >/dev/null 2>&1; then
    echo "FAIL: $f must not reference UDP 47808 (fieldbus owns BACnet/IP via host network)" >&2
    failed=1
  else
    echo "OK central-safe: $f (no 47808 publish)"
  fi
done

fieldbus_hits=0
for f in "${FIELDBUS_COMPOSE[@]}"; do
  if [[ ! -f "$f" ]]; then
    echo "FAIL: missing $f" >&2
    failed=1
    continue
  fi
  if rg -n 'fieldbus:' "$f" >/dev/null && rg -n 'network_mode:[[:space:]]*host' "$f" >/dev/null; then
    echo "OK fieldbus host-net: $f"
    fieldbus_hits=$((fieldbus_hits + 1))
  fi
done

if [[ "$fieldbus_hits" -lt 1 ]]; then
  echo "FAIL: expected at least one compose file with fieldbus + network_mode: host" >&2
  failed=1
fi

# Legacy monolithic compose must not re-bind 47808 on central services.
LEGACY=(
  docker/compose.edge.rust.yml
  docker-compose.bacnet-live.yml
)
for f in "${LEGACY[@]}"; do
  [[ -f "$f" ]] || continue
  if rg -n '47808' "$f" >/dev/null 2>&1; then
    echo "WARN: legacy $f still references 47808 — retire before cutover" >&2
  fi
done

if [[ "$failed" -ne 0 ]]; then
  exit 1
fi

echo "PASS: sole_bacnet_udp_owner"
