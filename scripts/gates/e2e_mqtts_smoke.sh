#!/usr/bin/env bash
# E2E scaffold: validate compose + contract/architecture gates without starting containers.
# Full fixture → Feather → FDD → UI → ack path requires Docker (see e2e_mqtts_feather.md).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

echo "== Open-FDD E2E MQTTS scaffold (no containers) =="

COMPOSE_FILES=(
  docker/compose.standalone.yml
  docker/compose.central.yml
  docker/compose.edge.yml
)

for f in "${COMPOSE_FILES[@]}"; do
  if [[ ! -f "$f" ]]; then
    echo "FAIL: missing compose file: $f" >&2
    exit 1
  fi
  echo "OK compose file: $f"
done

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  export OPENFDD_SITE_ID="${OPENFDD_SITE_ID:-local}"
  export OPENFDD_EDGE_ID="${OPENFDD_EDGE_ID:-fieldbus-1}"
  export OPENFDD_EDGE_KIT_DIR="${OPENFDD_EDGE_KIT_DIR:-$ROOT/deploy/mqtt/kits/${OPENFDD_SITE_ID}__${OPENFDD_EDGE_ID}}"
  export OPENFDD_MQTT_HOST="${OPENFDD_MQTT_HOST:-mqtt.example.com}"
  mkdir -p deploy/mqtt/certs deploy/mqtt/acl workspace
  docker compose -f docker/compose.standalone.yml config >/dev/null
  docker compose -f docker/compose.central.yml config >/dev/null
  # edge compose requires kit path even for config-only validation
  if [[ -d "$OPENFDD_EDGE_KIT_DIR" ]] || [[ -f deploy/mqtt/ca/ca.pem ]]; then
    docker compose -f docker/compose.edge.yml config >/dev/null
    echo "OK docker compose config (all stacks)"
  else
    echo "SKIP docker compose.edge.yml config (provision kit first)"
  fi
else
  echo "SKIP docker compose config (docker not available)"
fi

echo ""
echo "Running architecture + contract gates..."
bash "$ROOT/scripts/gates/run_all_gates.sh" "$@"

echo ""
echo "PASS: E2E scaffold (file + gate checks)"
echo ""
echo "DOCKER_REQUIRED for full E2E path:"
echo "  fixture publish → central Feather → FDD → UI → command ack"
echo "  See scripts/gates/e2e_mqtts_feather.md for step-by-step instructions."
