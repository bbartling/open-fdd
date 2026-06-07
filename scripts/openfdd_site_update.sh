#!/usr/bin/env bash
# Pull new GHCR images and recreate the Open-FDD stack (run on the edge host).
#
#   cd ~/open-fdd
#   ./scripts/openfdd_site_backup.sh
#   export NEW_TAG=2026.06.07-edge
#   ./scripts/openfdd_site_update.sh
#
# Never runs: docker compose down -v, volume prune, or workspace deletion.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

NEW_TAG="${NEW_TAG:-${OPENFDD_IMAGE_TAG:-}}"
if [[ -z "$NEW_TAG" ]]; then
  echo "Set NEW_TAG or OPENFDD_IMAGE_TAG (e.g. export NEW_TAG=2026.06.07-edge)" >&2
  exit 1
fi

COMPOSE_FILE="${COMPOSE_FILE:-}"
if [[ -z "$COMPOSE_FILE" ]]; then
  if [[ -f "$ROOT/docker-compose.yml" ]]; then
    COMPOSE_FILE="$ROOT/docker-compose.yml"
  elif [[ -f "$ROOT/docker/compose.edge.yml" ]]; then
    COMPOSE_FILE="$ROOT/docker/compose.edge.yml"
  else
    echo "No docker-compose.yml or docker/compose.edge.yml found under $ROOT" >&2
    exit 1
  fi
fi

export OPENFDD_IMAGE_TAG="$NEW_TAG"
COMPOSE=(docker compose -f "$COMPOSE_FILE")

IMAGES=(
  "ghcr.io/bbartling/openfdd-bridge:${NEW_TAG}"
  "ghcr.io/bbartling/openfdd-commission:${NEW_TAG}"
  "ghcr.io/bbartling/openfdd-mcp-rag:${NEW_TAG}"
)

echo "=== Open-FDD image update → ${NEW_TAG} ==="
echo "Compose file: $COMPOSE_FILE"
echo ""

echo "==> Verify images exist on GHCR"
for img in "${IMAGES[@]}"; do
  docker manifest inspect "$img" >/dev/null
  echo "  OK $img"
done

if [[ -f "$ROOT/docker-compose.yml" ]] && grep -q 'OPENFDD_IMAGE_TAG\|2026\.[0-9]' "$ROOT/docker-compose.yml" 2>/dev/null; then
  cp "$ROOT/docker-compose.yml" "$ROOT/docker-compose.yml.bak.$(date +%Y%m%d-%H%M%S)"
  if grep -q 'ghcr.io/bbartling/openfdd-bridge:' "$ROOT/docker-compose.yml"; then
    sed -i -E "s|(ghcr.io/bbartling/openfdd-[a-z-]+):[^\"'[:space:]]+|\1:${NEW_TAG}|g" "$ROOT/docker-compose.yml"
    echo "Updated image tags in docker-compose.yml"
  fi
fi

echo "==> Pull and recreate"
"${COMPOSE[@]}" pull
"${COMPOSE[@]}" up -d --force-recreate

echo ""
echo "==> Container status"
"${COMPOSE[@]}" ps
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}' | grep -E 'openfdd|NAMES' || true

echo ""
echo "==> Health"
if curl -sf --connect-timeout 5 http://127.0.0.1:8765/health; then
  echo ""
else
  echo "WARN: bridge /health not ready — check: docker compose -f $COMPOSE_FILE logs --since 5m bridge" >&2
fi

echo ""
echo "Done. BACnet poll still active if commission container is running (default)."
echo "Optional logs: docker compose -f $COMPOSE_FILE logs --since 10m"
