#!/usr/bin/env bash
# Easy button: pull newest vibe19 image and recreate the long-running container.
# Usage:
#   ./scripts/docker_update_vibe19.sh           # :latest (tip of develop)
#   ./scripts/docker_update_vibe19.sh develop   # same tip, branch tag
#   HOST_PORT=8501 ./scripts/docker_update_vibe19.sh latest
set -euo pipefail

TAG="${1:-latest}"
NAME="${CONTAINER_NAME:-vibe19}"
HOST_PORT="${HOST_PORT:-8502}"
IMAGE="ghcr.io/bbartling/vibe19:${TAG}"

echo "==> Pulling ${IMAGE}"
docker pull "${IMAGE}"

echo "==> Recreating container '${NAME}' on host port ${HOST_PORT}"
docker stop "${NAME}" 2>/dev/null || true
docker rm "${NAME}" 2>/dev/null || true
docker run -d --restart unless-stopped \
  -p "${HOST_PORT}:8501" \
  --name "${NAME}" \
  "${IMAGE}"

echo "==> Running:"
docker ps --filter "name=^/${NAME}$"
echo "Open http://localhost:${HOST_PORT}  (or http://<host-ip>:${HOST_PORT})"
echo "Note: a running container never auto-updates — re-run this script after GHCR builds."
