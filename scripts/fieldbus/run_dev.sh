#!/usr/bin/env bash
# Localdev launcher — pure Rust axum fieldbus.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

"${ROOT}/scripts/fieldbus/preflight_free_47808.sh"

export OPENFDD_FIELDBUS_CONFIG_DIR="${OPENFDD_FIELDBUS_CONFIG_DIR:-$ROOT/config/fieldbus}"
# Bind IP for BACnet; loopback-friendly default for CI / laptop. Override for OT LAN.
export OPENFDD_FIELDBUS_BIND="${OPENFDD_FIELDBUS_BIND:-${RUSTY_GATEWAY_BIND:-127.0.0.1}}"
export OPENFDD_FIELDBUS_OPENAPI="${OPENFDD_FIELDBUS_OPENAPI:-1}"

if [ -z "${OPENFDD_FIELDBUS_API_KEY:-${RUSTY_GATEWAY_API_KEY:-}}" ]; then
  export OPENFDD_FIELDBUS_API_KEY="$(openssl rand -hex 24 2>/dev/null || head -c 24 /dev/urandom | xxd -p -c 48)"
  echo "OPENFDD_FIELDBUS_API_KEY generated (save for Swagger Authorize)"
fi

echo "Starting openfdd-fieldbus (Swagger /docs) — config ${OPENFDD_FIELDBUS_CONFIG_DIR}"
cd "$ROOT"
exec cargo run --release -p openfdd-fieldbus
