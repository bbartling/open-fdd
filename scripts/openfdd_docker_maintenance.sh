#!/usr/bin/env bash
# Safe local Docker + build-artifact maintenance (does not stop running Open-FDD stack).
#
#   ./scripts/openfdd_docker_maintenance.sh
#   ./scripts/openfdd_docker_maintenance.sh --aggressive   # also remove unused images
#
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGGRESSIVE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --aggressive) AGGRESSIVE=1 ;;
    -h|--help)
      echo "Usage: $0 [--aggressive]"
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

echo "==> Before"
df -h / | tail -1
docker system df 2>/dev/null || true

echo "==> Remove root-owned Rust target dirs (Docker builds)"
if [[ -d "$ROOT/edge/target" || -d "$ROOT/target" ]]; then
  docker run --rm -v "$ROOT:/repo" alpine sh -c 'rm -rf /repo/edge/target /repo/target' 2>/dev/null || true
fi

echo "==> Prune dangling images, stopped containers, unused volumes"
docker container prune -f >/dev/null 2>&1 || true
docker image prune -f >/dev/null 2>&1 || true
docker volume prune -f >/dev/null 2>&1 || true

echo "==> Prune build cache"
docker builder prune -af >/dev/null 2>&1 || docker builder prune -af 2>/dev/null || true

if [[ "$AGGRESSIVE" == "1" ]]; then
  echo "==> Remove unused images (keeps images used by running containers)"
  docker image prune -a -f >/dev/null 2>&1 || true
fi

echo "==> After"
df -h / | tail -1
docker system df 2>/dev/null || true
echo "Done. Running containers were not stopped."
