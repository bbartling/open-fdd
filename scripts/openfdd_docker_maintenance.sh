#!/usr/bin/env bash
# Safe local Docker + build-artifact maintenance (does not stop running Open-FDD stack).
#
#   ./scripts/openfdd_docker_maintenance.sh
#   ./scripts/openfdd_docker_maintenance.sh --aggressive   # also remove unused images
#
# Volumes are never pruned by default. An intentional wipe requires
#   --prune-volumes --reset-db --i-understand-data-loss
# or --prune-volumes with OPENFDD_ALLOW_DESTRUCTIVE_DB=1.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_data_safety.sh
source "$ROOT/scripts/openfdd_data_safety.sh"

AGGRESSIVE=0
PRUNE_VOLUMES=0
RESET_DB=0
UNDERSTAND=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --aggressive) AGGRESSIVE=1 ;;
    --prune-volumes) PRUNE_VOLUMES=1 ;;
    --reset-db) RESET_DB=1 ;;
    --i-understand-data-loss) UNDERSTAND=1 ;;
    -h|--help)
      cat <<'EOF'
Usage: openfdd_docker_maintenance.sh [--aggressive] [--prune-volumes --reset-db --i-understand-data-loss]

Default: prune dangling images, stopped containers, and build cache.
Does not stop the stack and does not prune volumes.

--prune-volumes   Delete unused Docker volumes. Refuses unless
                  --reset-db --i-understand-data-loss are both set, or
                  OPENFDD_ALLOW_DESTRUCTIVE_DB=1 is set.
EOF
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

echo "==> Prune dangling images and stopped containers"
docker container prune -f >/dev/null 2>&1 || true
docker image prune -f >/dev/null 2>&1 || true

if [[ "$PRUNE_VOLUMES" == "1" ]]; then
  if openfdd_data_loss_opt_in "$RESET_DB" "$UNDERSTAND"; then
    echo "WARNING: DATA LOSS — docker volume prune will delete unused volumes." >&2
    docker volume prune -f
  else
    echo "REFUSED: --prune-volumes deletes database volumes." >&2
    echo "Re-run with --prune-volumes --reset-db --i-understand-data-loss" >&2
    echo "or set OPENFDD_ALLOW_DESTRUCTIVE_DB=1 with --prune-volumes." >&2
    exit 1
  fi
else
  echo "==> Keeping Docker volumes (database data is not pruned)"
fi

echo "==> Prune build cache"
docker builder prune -af >/dev/null 2>&1 || docker builder prune -af 2>/dev/null || true

if [[ "$AGGRESSIVE" == "1" ]]; then
  echo "==> Remove unused images (keeps images used by running containers)"
  docker image prune -a -f >/dev/null 2>&1 || true
fi

echo "==> After"
df -h / | tail -1
docker system df 2>/dev/null || true
echo "Done. Running containers were not stopped. Volumes were not pruned unless --prune-volumes was accepted."
