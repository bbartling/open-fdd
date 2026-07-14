#!/usr/bin/env bash
# Local dev launcher — pure Rust axum sidecar.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

"${ROOT}/scripts/preflight_free_47808.sh"

export OPENFDD_FIELDBUS_CONFIG_DIR="${OPENFDD_FIELDBUS_CONFIG_DIR:-$ROOT/config}"
export OPENFDD_FIELDBUS_BIND="${OPENFDD_FIELDBUS_BIND:-${RUSTY_GATEWAY_BIND:-192.168.204.55}}"
export OPENFDD_FIELDBUS_OPENAPI="${OPENFDD_FIELDBUS_OPENAPI:-1}"

if [ -z "${OPENFDD_FIELDBUS_API_KEY:-${RUSTY_GATEWAY_API_KEY:-}}" ]; then
  export OPENFDD_FIELDBUS_API_KEY="$(openssl rand -hex 24 2>/dev/null || head -c 24 /dev/urandom | xxd -p -c 48)"
  echo "OPENFDD_FIELDBUS_API_KEY generated (save for Swagger Authorize)"
fi

echo "Starting Rust gateway on http://0.0.0.0:8080 (Swagger /docs)"
cd rust-api
exec cargo run --release
