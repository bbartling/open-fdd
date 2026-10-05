#!/usr/bin/env bash
# S07 — fail-closed static render for selected-OT + HTTPS (no daemon/start).
# Synthetic unique secrets only; does not pull or boot images.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

export OPENFDD_IMAGE_TAG="${OPENFDD_IMAGE_TAG:-sha-215e159}"
export OPENFDD_CENTRAL_IMAGE="${OPENFDD_CENTRAL_IMAGE:-ghcr.io/bbartling/openfdd-central:${OPENFDD_IMAGE_TAG}}"
export OPENFDD_WEB_IMAGE="${OPENFDD_WEB_IMAGE:-ghcr.io/bbartling/openfdd-web:${OPENFDD_IMAGE_TAG}}"
export OPENFDD_HAYSTACK_IMAGE="${OPENFDD_HAYSTACK_IMAGE:-ghcr.io/bbartling/openfdd-haystack:${OPENFDD_IMAGE_TAG}}"
export OPENFDD_JWT_SECRET="${OPENFDD_JWT_SECRET:-synth-jwt-secret-32chars-minimum!!}"
export OPENFDD_ADMIN_PASSWORD="${OPENFDD_ADMIN_PASSWORD:-synth-admin-password-xx}"
export OPENFDD_LOCAL_INGEST_TOKEN="${OPENFDD_LOCAL_INGEST_TOKEN:-synth-local-ingest-token-xx}"
export OPENFDD_CONNECTOR_API_KEY="${OPENFDD_CONNECTOR_API_KEY:-synth-connector-api-key-xx}"
export OPENFDD_SITE_ID="${OPENFDD_SITE_ID:-SYNTH_SITE_A}"
export OPENFDD_HAYSTACK_BASE_URL="${OPENFDD_HAYSTACK_BASE_URL:-https://haystack.example.invalid/}"
export OPENFDD_PUBLIC_HOST="${OPENFDD_PUBLIC_HOST:-localhost}"
export OPENFDD_CADDY_TLS_MODE="${OPENFDD_CADDY_TLS_MODE:-local_ca}"
export OPENFDD_CADDYFILE_SUFFIX="${OPENFDD_CADDYFILE_SUFFIX:-.local_ca}"

echo "== render ot_local_haystack + standalone.https =="
docker compose \
  -f docker/compose.ot_local_haystack.yml \
  -f docker/compose.standalone.https.yml \
  config --quiet
echo "ok: haystack+https"

# Ensure broker-free: no mqtt service in rendered project.
if docker compose \
  -f docker/compose.ot_local_haystack.yml \
  -f docker/compose.standalone.https.yml \
  config --services | grep -qx mqtt; then
  echo "FAIL: mqtt service must not appear in selected-OT HTTPS render" >&2
  exit 1
fi
echo "ok: no mqtt service"

echo "== render ot_local_bacnet_modbus + standalone.https =="
# Bacnet file may require additional vars; set common ones.
export OPENFDD_BACNET_DEVICE_ID="${OPENFDD_BACNET_DEVICE_ID:-1000}"
docker compose \
  -f docker/compose.ot_local_bacnet_modbus.yml \
  -f docker/compose.standalone.https.yml \
  config --quiet
echo "ok: bacnet+https"

echo "S07 selected-OT HTTPS compose render PASS"
