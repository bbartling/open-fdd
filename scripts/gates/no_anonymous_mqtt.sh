#!/usr/bin/env bash
# Mosquitto must reject anonymous clients and require client certificates.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONF="$ROOT/services/mqtt/mosquitto.conf"

echo "== gate: no_anonymous_mqtt =="

if [[ ! -f "$CONF" ]]; then
  echo "FAIL: missing $CONF" >&2
  exit 1
fi

if ! grep -nE '^[[:space:]]*allow_anonymous[[:space:]]+false' "$CONF" >/dev/null; then
  echo "FAIL: $CONF must set allow_anonymous false" >&2
  exit 1
fi

if ! grep -nE '^[[:space:]]*require_certificate[[:space:]]+true' "$CONF" >/dev/null; then
  echo "FAIL: $CONF must set require_certificate true" >&2
  exit 1
fi

echo "PASS: no_anonymous_mqtt"
