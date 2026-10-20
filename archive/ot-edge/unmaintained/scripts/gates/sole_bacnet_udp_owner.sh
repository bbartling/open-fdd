#!/usr/bin/env bash
# Product compose must not publish BACnet/IP UDP 47808. Field containers are archived.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

echo "== gate: sole_bacnet_udp_owner =="

PRODUCT_COMPOSE=(
  docker/compose.portal.yml
  docker/compose.central.yml
  docker/compose.csv.yml
  docker/compose.react.yml
)

failed=0

for f in "${PRODUCT_COMPOSE[@]}"; do
  if [[ ! -f "$f" ]]; then
    echo "FAIL: missing $f" >&2
    failed=1
    continue
  fi
  if grep -nE '47808|fieldbus:' "$f" >/dev/null 2>&1; then
    echo "FAIL: $f must not publish BACnet/IP or a fieldbus service" >&2
    failed=1
  else
    echo "OK product compose: $f"
  fi
done

if [[ -e services/fieldbus || -f docker/compose.edge.yml ]]; then
  echo "FAIL: live fieldbus tree or compose.edge.yml must stay archived" >&2
  failed=1
fi

if [[ "$failed" -ne 0 ]]; then
  exit 1
fi

echo "PASS: sole_bacnet_udp_owner"
