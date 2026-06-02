#!/usr/bin/env bash
# Safe Docker disk maintenance for Open-FDD edge hosts.
# Never prunes volumes (feather/historian live under bind-mounted workspace/).
#
# Env:
#   PRUNE_UNUSED_IMAGES=1   Remove all images not referenced by a running container
#   PRUNE_BUILD_CACHE=1     docker builder prune (BuildKit cache only)
#   REMOVE_IMAGE_TAR=1      Delete the loaded .tar.gz bundle after deploy
#   IMAGE_TAR_PATH=         Path to openfdd-images-*.tar.gz on the edge host
set -euo pipefail

log() { printf '%s\n' "$*"; }

log "==> Docker disk usage (before)"
docker system df 2>/dev/null || true

log "==> Prune stopped containers"
docker container prune -f

log "==> Prune unused networks"
docker network prune -f

log "==> Prune dangling images"
docker image prune -f

if [[ "${PRUNE_BUILD_CACHE:-0}" == "1" ]]; then
  log "==> Prune build cache (older than 7 days)"
  docker builder prune -f --filter "until=168h" 2>/dev/null || docker builder prune -f 2>/dev/null || true
fi

if [[ "${PRUNE_UNUSED_IMAGES:-0}" == "1" ]]; then
  log "==> Prune unused images (not used by any container — safe after compose up)"
  docker image prune -a -f
fi

if [[ "${REMOVE_IMAGE_TAR:-0}" == "1" && -n "${IMAGE_TAR_PATH:-}" && -f "${IMAGE_TAR_PATH}" ]]; then
  log "==> Remove image bundle: ${IMAGE_TAR_PATH}"
  rm -f "${IMAGE_TAR_PATH}"
fi

log "==> Docker disk usage (after)"
docker system df 2>/dev/null || true
