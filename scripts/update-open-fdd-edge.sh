#!/usr/bin/env bash
# Run ON the edge host (or via ansible ad-hoc) — pull GHCR images and restart compose.
#
#   OPENFDD_IMAGE_TAG=latest /opt/open-fdd/update-open-fdd.sh
#   cd ~/open-fdd && OPENFDD_IMAGE_TAG=latest ./scripts/update-open-fdd-edge.sh
#
# Application code lives in containers (ghcr.io/bbartling/openfdd-*). This script
# never receives Python, React, or rule source from a developer workstation.
#
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE="${OPENFDD_COMPOSE_FILE:-${ROOT}/docker-compose.yml}"
TAG="${OPENFDD_IMAGE_TAG:-latest}"

export OPENFDD_IMAGE_TAG="$TAG"

if [[ ! -f "$COMPOSE" ]]; then
  echo "Missing compose file: $COMPOSE" >&2
  exit 1
fi

echo "==> Open-FDD edge update (GHCR tag=${TAG})"
docker compose -f "$COMPOSE" pull
docker compose -f "$COMPOSE" up -d --remove-orphans
docker compose -f "$COMPOSE" ps
echo "==> Done. Runtime data remains under ${ROOT}/workspace/"
