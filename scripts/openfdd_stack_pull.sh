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
    docker pull "$OPENFDD_WEB_IMAGE"
    docker pull "$OPENFDD_FIELDBUS_IMAGE"
    docker pull "$OPENFDD_MQTT_IMAGE"
    ;;
  central)
    docker pull "$OPENFDD_CENTRAL_IMAGE"
    docker pull "$OPENFDD_WEB_IMAGE"
    docker pull "$OPENFDD_MQTT_IMAGE"
    ;;
  edge)
    docker pull "$OPENFDD_FIELDBUS_IMAGE"
    ;;
  csv)
    docker pull "$OPENFDD_CENTRAL_IMAGE"
    docker pull "$OPENFDD_WEB_IMAGE"
    ;;
  react)
    docker pull "$OPENFDD_CENTRAL_IMAGE"
    docker pull "$OPENFDD_MQTT_IMAGE"
    if ! docker pull "$OPENFDD_WEB_IMAGE" 2>/dev/null; then
      echo "WARN: $OPENFDD_WEB_IMAGE not in registry — build web locally on up" >&2
    fi
    ;;
  react-ot)
    docker pull "$OPENFDD_CENTRAL_IMAGE"
    docker pull "$OPENFDD_MQTT_IMAGE"
    docker pull "$OPENFDD_FIELDBUS_IMAGE"
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
    echo "Usage: $0 [standalone|central|edge|csv|react|react-ot|mcp|all]" >&2
    exit 2
    ;;
esac
echo "OK pull complete"
