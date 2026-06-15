#!/usr/bin/env bash
# Fix root-owned files under workspace/ on an edge host (Docker bridge/commission writes).
#
#   cd ~/open-fdd
#   ./scripts/fix_edge_workspace_permissions.sh
#
# Safe no-op when compose or bridge container is not running.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

COMPOSE_FILE="${COMPOSE_FILE:-}"
if [[ -z "$COMPOSE_FILE" ]]; then
  if [[ -f "$ROOT/docker-compose.yml" ]]; then
    COMPOSE_FILE="$ROOT/docker-compose.yml"
  elif [[ -f "$ROOT/docker/compose.edge.yml" ]]; then
    COMPOSE_FILE="$ROOT/docker/compose.edge.yml"
  fi
fi

UID_GID="$(id -u):$(id -g)"

if ! command -v docker >/dev/null 2>&1 || [[ -z "$COMPOSE_FILE" || ! -f "$COMPOSE_FILE" ]]; then
  echo "skip: docker compose not available (${COMPOSE_FILE:-missing})"
  exit 0
fi

cid="$(docker compose -f "$COMPOSE_FILE" ps -q bridge 2>/dev/null | head -1 || true)"
if [[ -z "$cid" ]]; then
  echo "skip: bridge container not running"
  exit 0
fi

docker exec -u root "$cid" chown -R "$UID_GID" \
  /var/openfdd/workspace/data \
  /var/openfdd/workspace/bacnet 2>/dev/null || true

echo "workspace data + bacnet owned by ${UID_GID} (via bridge container)"
