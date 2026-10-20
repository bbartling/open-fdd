#!/usr/bin/env bash
# Product stack file smoke: portal central + React web.
# Does not build or require the archived MQTT broker or fieldbus images.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

echo "== Open-FDD product stack file smoke =="
echo "root=$ROOT"

COMPOSE_FILES=(
  docker/compose.portal.yml
  docker/compose.central.yml
  docker/compose.csv.yml
  docker/compose.react.yml
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
  frontend/web/Dockerfile
)

for f in "${DOCKERFILES[@]}"; do
  if [[ ! -f "$f" ]]; then
    echo "FAIL: missing Dockerfile: $f" >&2
    exit 1
  fi
  echo "OK dockerfile: $f"
done

if [[ -e services/fieldbus || -e services/mqtt ]]; then
  echo "FAIL: fieldbus and mqtt broker must stay under archive/ot-edge/unmaintained" >&2
  exit 1
fi
echo "OK no live fieldbus or mqtt broker tree"

if [[ -d services/ui ]]; then
  echo "FAIL: services/ui must not exist (use frontend/web)" >&2
  exit 1
fi
echo "OK no services/ui tree"

if [[ ! -f frontend/web/package.json ]]; then
  echo "FAIL: frontend/web/package.json missing" >&2
  exit 1
fi
echo "OK React product UI"

if [[ ! -f tools/wattlab_export/agent_afdd.py ]]; then
  echo "FAIL: tools/wattlab_export/agent_afdd.py missing" >&2
  exit 1
fi
echo "OK WattLab exporter"

if [[ ! -f docker/VERSION_MANIFEST.md ]]; then
  echo "FAIL: docker/VERSION_MANIFEST.md missing" >&2
  exit 1
fi
echo "OK version manifest"

if [[ ! -f crates/openfdd_mqtt/Cargo.toml ]]; then
  echo "FAIL: crates/openfdd_mqtt missing (central MQTT ingest bridge)" >&2
  exit 1
fi
echo "OK central MQTT ingest bridge crate"

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  echo "Docker available — validating product compose config (no containers started)"
  export OPENFDD_JWT_SECRET="${OPENFDD_JWT_SECRET:-ci-compose-config-secret-not-for-prod}"
  export OPENFDD_ADMIN_PASSWORD="${OPENFDD_ADMIN_PASSWORD:-ci-compose-admin-not-for-prod}"
  docker compose -f docker/compose.portal.yml config >/dev/null
  docker compose -f docker/compose.central.yml config >/dev/null
  docker compose -f docker/compose.react.yml config >/dev/null
  echo "OK docker compose config"
else
  echo "SKIP docker compose config (docker not available or not running)"
fi

echo "PASS: product stack file smoke"
