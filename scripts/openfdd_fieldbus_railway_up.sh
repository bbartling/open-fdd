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

# Railway field identity wins over local .env (lab/fieldbus-1) unless opted out.
export OPENFDD_IMAGE_TAG="$SHA"
export OPENFDD_FIELDBUS_IMAGE="ghcr.io/bbartling/openfdd-fieldbus:${SHA}"
if [[ "${OPENFDD_FIELD_IDENTITY_FROM_ENV:-0}" != "1" ]]; then
  export OPENFDD_MQTT_HOST=reseau.proxy.rlwy.net
  export OPENFDD_MQTT_PORT=44763
  export OPENFDD_SITE_ID=bldg2
  export OPENFDD_EDGE_ID=bensbench-1
fi
export OPENFDD_EDGE_KIT_DIR="${OPENFDD_EDGE_KIT_DIR:-$ROOT/deploy/mqtt/kits/${OPENFDD_SITE_ID}__${OPENFDD_EDGE_ID}}"

if [[ ! -f "$OPENFDD_EDGE_KIT_DIR/ca.pem" || ! -f "$OPENFDD_EDGE_KIT_DIR/edge.cert.pem" ]]; then
  echo "ERROR: edge kit missing at $OPENFDD_EDGE_KIT_DIR (POST /api/mqtt/edge-kits on Railway)" >&2
  exit 2
fi

echo "== stop local react-ot hub (fieldbus-only on this host) =="
docker compose -f "$ROOT/docker/compose.react.yml" \
  -f "$ROOT/docker/compose.react.fieldbus.yml" \
  down --remove-orphans 2>/dev/null || true

echo "== pull fieldbus $OPENFDD_FIELDBUS_IMAGE =="
docker pull "$OPENFDD_FIELDBUS_IMAGE"

echo "== up edge → $OPENFDD_MQTT_HOST:$OPENFDD_MQTT_PORT site=$OPENFDD_SITE_ID edge=$OPENFDD_EDGE_ID =="
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
