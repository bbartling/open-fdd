#!/usr/bin/env bash
# The Mosquitto broker image is archived. The product tree must not ship a live broker.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

echo "== gate: no_anonymous_mqtt =="

if [[ -e "$ROOT/services/mqtt" ]]; then
  echo "FAIL: services/mqtt must stay archived (archive/ot-edge/unmaintained/services/mqtt)" >&2
  exit 1
fi

portal="$ROOT/docker/compose.portal.yml"
if grep -nE '^[[:space:]]*mqtt:' "$portal" >/dev/null; then
  echo "FAIL: portal compose must not start an MQTT broker" >&2
  exit 1
fi

echo "PASS: no_anonymous_mqtt"
