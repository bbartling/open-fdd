#!/usr/bin/env bash
# Validate standalone MQTTS stack files and optionally provision missing MQTT certs.
# Does not require Docker to be running — file and cargo checks only.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

echo "== Open-FDD standalone MQTTS smoke (files + provision) =="
echo "root=$ROOT"

COMPOSE_FILES=(
  docker/compose.standalone.yml
  docker/compose.central.yml
  docker/compose.edge.yml
  docker/compose.csv.yml
)

for f in "${COMPOSE_FILES[@]}"; do
  if [[ ! -f "$f" ]]; then
    echo "FAIL: missing compose file: $f" >&2
    exit 1
  fi
  echo "OK compose: $f"
done

DOCKERFILES=(
  services/central/Dockerfile
  workspace/dashboard/Dockerfile
  services/fieldbus/Dockerfile
  services/mqtt/Dockerfile
)

for f in "${DOCKERFILES[@]}"; do
  if [[ ! -f "$f" ]]; then
    echo "FAIL: missing Dockerfile: $f" >&2
    exit 1
  fi
  echo "OK dockerfile: $f"
done

if [[ ! -f workspace/dashboard/package.json ]]; then
  echo "FAIL: workspace/dashboard/package.json missing" >&2
  exit 1
fi
echo "OK dashboard package.json"

if [[ ! -f workspace/dashboard/.env.example ]]; then
  echo "FAIL: workspace/dashboard/.env.example missing (VITE_API_BASE)" >&2
  exit 1
fi
echo "OK dashboard .env.example"

if [[ ! -f docker/VERSION_MANIFEST.md ]]; then
  echo "FAIL: docker/VERSION_MANIFEST.md missing" >&2
  exit 1
fi
echo "OK version manifest"

SITE_ID="${OPENFDD_SITE_ID:-local}"
EDGE_ID="${OPENFDD_EDGE_ID:-fieldbus-1}"
KIT_DIR="deploy/mqtt/kits/${SITE_ID}__${EDGE_ID}"
CA_PEM="deploy/mqtt/ca/ca.pem"

need_provision=0
if [[ ! -f "$CA_PEM" ]] || [[ ! -f "$KIT_DIR/edge.cert.pem" ]]; then
  need_provision=1
  echo "MQTT certs missing — will run openfdd-provision edge"
fi

if [[ "$need_provision" -eq 1 ]]; then
  if ! command -v cargo >/dev/null 2>&1; then
    echo "WARN: cargo not found; skipping provision (certs still missing)" >&2
  else
    echo "Running: cargo run -p openfdd_mqtt --bin openfdd-provision -- edge \\"
    echo "  --site-id $SITE_ID --edge-id $EDGE_ID --out-dir deploy/mqtt"
    cargo run -p openfdd_mqtt --bin openfdd-provision -- edge \
      --site-id "$SITE_ID" \
      --edge-id "$EDGE_ID" \
      --out-dir deploy/mqtt
    if [[ -f "$KIT_DIR/ca.pem" ]]; then
      echo "OK provision kit: $KIT_DIR"
    else
      echo "FAIL: provision did not create $KIT_DIR" >&2
      exit 1
    fi
  fi
else
  echo "OK MQTT certs present ($CA_PEM, $KIT_DIR)"
fi

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  echo "Docker available — validating compose config (no containers started)"
  export OPENFDD_SITE_ID="$SITE_ID"
  export OPENFDD_EDGE_ID="$EDGE_ID"
  export OPENFDD_EDGE_KIT_DIR="${OPENFDD_EDGE_KIT_DIR:-$ROOT/$KIT_DIR}"
  export OPENFDD_MQTT_HOST="${OPENFDD_MQTT_HOST:-127.0.0.1}"
  mkdir -p deploy/mqtt/certs deploy/mqtt/acl workspace "$OPENFDD_EDGE_KIT_DIR"
  docker compose -f docker/compose.standalone.yml config >/dev/null
  docker compose -f docker/compose.central.yml config >/dev/null
  docker compose -f docker/compose.edge.yml config >/dev/null
  echo "OK docker compose config"
else
  echo "SKIP docker compose config (docker not available or not running)"
fi

echo "PASS: standalone MQTTS file smoke"
