#!/usr/bin/env bash
# Pull GHCR stack nightlies (or OPENFDD_IMAGE_TAG) for compose recipes.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_stack_lib.sh
source "$ROOT/scripts/openfdd_stack_lib.sh"

RECIPE="${1:-portal}"
case "$RECIPE" in
  standalone|edge|react-ot)
    echo "4.0 does not pull openfdd-fieldbus (recipe=$RECIPE)." >&2
    echo "The archive restore lane pins digests and does not pull or start containers." >&2
    echo "  OPENFDD_OT_ARCHIVE_RESTORE=1 ./archive/ot-edge/unqualified-cdaa4f15/recipes/restore-isolated.sh --replay" >&2
    exit 2
    ;;
esac
openfdd_stack_export_image_env

echo "==> Pulling stack images (tag=${OPENFDD_IMAGE_TAG:-nightly}) for recipe=${RECIPE}"
case "$RECIPE" in
  central)
    docker pull "$OPENFDD_CENTRAL_IMAGE"
    docker pull "$OPENFDD_WEB_IMAGE"
    ;;
  csv|portal)
    docker pull "$OPENFDD_CENTRAL_IMAGE"
    docker pull "$OPENFDD_WEB_IMAGE"
    ;;
  react)
    docker pull "$OPENFDD_CENTRAL_IMAGE"
    if ! docker pull "$OPENFDD_WEB_IMAGE" 2>/dev/null; then
      echo "WARN: $OPENFDD_WEB_IMAGE not in registry — build web locally on up" >&2
    fi
    ;;
  mcp)
    docker pull "$OPENFDD_MCP_IMAGE"
    ;;
  all)
    for img in $(openfdd_stack_images); do
      docker pull "$img"
    done
    ;;
  *)
    echo "Usage: $0 [portal|central|csv|react|mcp|all]" >&2
    exit 2
    ;;
esac
echo "OK pull complete"
