#!/usr/bin/env bash
# Local Docker maintenance. Does not stop a running Open-FDD stack.
#
# Volumes are kept. `docker volume prune` runs only with both:
#   --prune-volumes --i-understand-data-loss
# or --prune-volumes plus OPENFDD_ALLOW_DESTRUCTIVE_DB=1.
#
#   ./scripts/openfdd_docker_maintenance.sh
#   ./scripts/openfdd_docker_maintenance.sh --aggressive
#   ./scripts/openfdd_docker_maintenance.sh --dry-run
#
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/data_safe.sh
source "$ROOT/scripts/lib/data_safe.sh"

AGGRESSIVE=0
PRUNE_VOLUMES=0
ACK=0
DRY_RUN=0
if openfdd_env_flag_on "${OPENFDD_ALLOW_DESTRUCTIVE_DB:-}"; then
  ACK=1
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --aggressive) AGGRESSIVE=1 ;;
    --prune-volumes) PRUNE_VOLUMES=1 ;;
    --i-understand-data-loss) ACK=1 ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help)
      cat <<EOF
Usage: $0 [--aggressive] [--dry-run] [--prune-volumes --i-understand-data-loss]

Default: prune stopped containers and dangling images. Named volumes stay.
--prune-volumes deletes unused Docker volumes only together with
--i-understand-data-loss or OPENFDD_ALLOW_DESTRUCTIVE_DB=1.
EOF
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

DECISION="$(openfdd_volume_prune_decision "$PRUNE_VOLUMES" "$ACK")"
if [[ "$DRY_RUN" == "1" ]]; then
  echo "data_safe_action=$DECISION"
  if [[ "$DECISION" == "refuse" ]]; then
    echo "REFUSING: docker volume prune can delete an unused Timescale volume." >&2
    echo "Re-run with --prune-volumes --i-understand-data-loss or OPENFDD_ALLOW_DESTRUCTIVE_DB=1." >&2
    exit 2
  fi
  exit 0
fi

if [[ "$DECISION" == "refuse" ]]; then
  echo "REFUSING: docker volume prune can delete an unused Timescale volume." >&2
  echo "Re-run with --prune-volumes --i-understand-data-loss or OPENFDD_ALLOW_DESTRUCTIVE_DB=1." >&2
  echo "data_safe_action=refuse" >&2
  exit 2
fi

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
if [[ "$DECISION" == "prune" ]]; then
  echo "WARNING: pruning unused Docker volumes. An unused openfdd-timescale volume will be deleted." >&2
  docker volume prune -f >/dev/null 2>&1 || true
else
  echo "Skipping docker volume prune (data-safe default)."
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
echo "Done. Running containers were not stopped. Volumes were not pruned unless --prune-volumes was acknowledged."
