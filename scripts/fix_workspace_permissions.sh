#!/usr/bin/env bash
# Fix root-owned files under workspace/ after Docker BACnet/bridge writes (local dev).
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE="${REPO_ROOT}/docker/compose.dev.yml"
UID_GID="$(id -u):$(id -g)"
docker compose -f "$COMPOSE" exec -u root bridge \
  chown -R "$UID_GID" /var/openfdd/workspace/data /var/openfdd/workspace/bacnet
echo "workspace data + bacnet owned by $UID_GID"
