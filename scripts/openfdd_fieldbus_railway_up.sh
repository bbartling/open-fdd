#!/usr/bin/env bash
# Bring up bensbench x86 fieldbus only → Railway MQTTS. Stops local react-ot hub.
# Usage: ./scripts/openfdd_fieldbus_railway_up.sh [sha-<7>]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SHA="${1:-${OPENFDD_IMAGE_TAG:-}}"
[[ -n "$SHA" ]] || { echo "ERROR: pass sha-<7> or set OPENFDD_IMAGE_TAG" >&2; exit 2; }

if [[ -f "$ROOT/.env" ]]; then
  # shellcheck disable=SC1091
  set -a && source "$ROOT/.env" && set +a
fi

# Railway field identity wins over local .env / parent-shell pollution unless
# OPENFDD_FIELD_IDENTITY_FROM_ENV=1 is set *intentionally after* this block.
export OPENFDD_IMAGE_TAG="$SHA"
export OPENFDD_FIELDBUS_IMAGE="ghcr.io/bbartling/openfdd-fieldbus:${SHA}"
# Parent shells sometimes leave OPENFDD_FIELD_IDENTITY_FROM_ENV=1 from manual
# experiments — only honor it when OPENFDD_RAILWAY_USE_ENV_IDENTITY=1.
if [[ "${OPENFDD_RAILWAY_USE_ENV_IDENTITY:-0}" == "1" ]]; then
  : # keep sourced OPENFDD_* site/edge/tenant/building
else
  export OPENFDD_MQTT_HOST=reseau.proxy.rlwy.net
  export OPENFDD_MQTT_PORT=44763
  # Wave N+ Railway hub is multi_tenant=true — hard-set ACME tenant path
  # (do not keep local .env site/building/edge — those reject under MT ingest).
  # Live ACME OT edge is vim-1 (private); bensbench x86 uses pi-1 under ACME.
  export OPENFDD_SITE_ID=ACME
  export OPENFDD_EDGE_ID="${OPENFDD_RAILWAY_EDGE_ID:-pi-1}"
  export OPENFDD_TENANT_ID=acme
  export OPENFDD_BUILDING_ID=ACME
fi
export OPENFDD_TENANT_ID="${OPENFDD_TENANT_ID:-acme}"
export OPENFDD_BUILDING_ID="${OPENFDD_BUILDING_ID:-ACME}"
export OPENFDD_EDGE_KIT_DIR="${OPENFDD_EDGE_KIT_DIR:-$ROOT/deploy/mqtt/kits/${OPENFDD_SITE_ID}__${OPENFDD_EDGE_ID}}"

if [[ ! -f "$OPENFDD_EDGE_KIT_DIR/ca.pem" || ! -f "$OPENFDD_EDGE_KIT_DIR/edge.cert.pem" ]]; then
  echo "ERROR: edge kit missing at $OPENFDD_EDGE_KIT_DIR" >&2
  echo "  Restore MT kit: OPENFDD_API_BASE=https://… OPENFDD_ADMIN_PASSWORD=… \\" >&2
  echo "    ./scripts/openfdd_restore_edge_kit.sh ${OPENFDD_SITE_ID} ${OPENFDD_EDGE_ID}" >&2
  echo "  (POST body must include tenant_id=${OPENFDD_TENANT_ID} building_id=${OPENFDD_BUILDING_ID})" >&2
  exit 2
fi

echo "== stop local react-ot hub (fieldbus-only on this host) =="
docker compose -f "$ROOT/docker/compose.react.yml" \
  -f "$ROOT/docker/compose.react.fieldbus.yml" \
  down --remove-orphans 2>/dev/null || true

echo "== pull fieldbus $OPENFDD_FIELDBUS_IMAGE =="
docker pull "$OPENFDD_FIELDBUS_IMAGE"

echo "== up edge → $OPENFDD_MQTT_HOST:$OPENFDD_MQTT_PORT tenant=$OPENFDD_TENANT_ID building=$OPENFDD_BUILDING_ID edge=$OPENFDD_EDGE_ID =="
docker compose -f "$ROOT/docker/compose.edge.yml" \
  -f "$ROOT/docker/compose.edge.railway.yml" \
  up -d --no-build --force-recreate

for _ in $(seq 1 18); do
  if curl -sf --max-time 4 http://127.0.0.1:8081/health >/dev/null; then
    echo "OK fieldbus http://127.0.0.1:8081/health"
    exit 0
  fi
  sleep 2
done
echo "ERROR: fieldbus health not ready" >&2
exit 1
