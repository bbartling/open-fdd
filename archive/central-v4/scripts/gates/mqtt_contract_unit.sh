#!/usr/bin/env bash
# MQTT + shared contract unit tests (Rust).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

echo "== gate: mqtt_contract_unit =="

if ! command -v cargo >/dev/null 2>&1; then
  echo "FAIL: cargo not found" >&2
  exit 1
fi

cargo test -p openfdd_contracts -p openfdd_mqtt
echo "PASS: mqtt_contract_unit"
