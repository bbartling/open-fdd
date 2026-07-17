#!/usr/bin/env bash
# Pull GHCR stack nightlies (or OPENFDD_IMAGE_TAG) for compose recipes.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_stack_lib.sh
source "$ROOT/scripts/openfdd_stack_lib.sh"

RECIPE="${1:-standalone}"
openfdd_stack_export_image_env

echo "==> Pulling stack images (tag=${OPENFDD_IMAGE_TAG:-nightly}) for recipe=${RECIPE}"
case "$RECIPE" in
  standalone)
    docker pull "$OPENFDD_CENTRAL_IMAGE"
    docker pull "$OPENFDD_UI_IMAGE"
    docker pull "$OPENFDD_FIELDBUS_IMAGE"
    docker pull "$OPENFDD_MQTT_IMAGE"
    ;;
  central)
    docker pull "$OPENFDD_CENTRAL_IMAGE"
    docker pull "$OPENFDD_UI_IMAGE"
    docker pull "$OPENFDD_MQTT_IMAGE"
    ;;
  edge)
    docker pull "$OPENFDD_FIELDBUS_IMAGE"
    ;;
  csv)
    docker pull "$OPENFDD_CENTRAL_IMAGE"
    docker pull "$OPENFDD_UI_IMAGE"
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
    echo "Usage: $0 [standalone|central|edge|csv|mcp|all]" >&2
    exit 2
    ;;
esac
echo "OK pull complete"
