#!/usr/bin/env bash
# Shared helpers for Open-FDD stack compose recipes (central/ui/fieldbus/mqtt).
set -euo pipefail

openfdd_stack_root() {
  cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd
}

openfdd_stack_recipe_file() {
  local recipe="${1:-standalone}"
  local root
  root="$(openfdd_stack_root)"
  case "$recipe" in
    standalone) echo "$root/docker/compose.standalone.yml" ;;
    central) echo "$root/docker/compose.central.yml" ;;
    edge) echo "$root/docker/compose.edge.yml" ;;
    csv) echo "$root/docker/compose.csv.yml" ;;
    *)
      echo "ERROR: unknown recipe '$recipe' (standalone|central|edge|csv)" >&2
      return 2
      ;;
  esac
}

openfdd_stack_images() {
  local tag="${OPENFDD_IMAGE_TAG:-nightly}"
  echo "ghcr.io/bbartling/openfdd-central:${tag}"
  echo "ghcr.io/bbartling/openfdd-ui:${tag}"
  echo "ghcr.io/bbartling/openfdd-fieldbus:${tag}"
  echo "ghcr.io/bbartling/openfdd-mqtt:${tag}"
  echo "ghcr.io/bbartling/openfdd-mcp:${tag}"
}

openfdd_stack_export_image_env() {
  local tag="${OPENFDD_IMAGE_TAG:-nightly}"
  export OPENFDD_CENTRAL_IMAGE="${OPENFDD_CENTRAL_IMAGE:-ghcr.io/bbartling/openfdd-central:${tag}}"
  export OPENFDD_UI_IMAGE="${OPENFDD_UI_IMAGE:-ghcr.io/bbartling/openfdd-ui:${tag}}"
  export OPENFDD_FIELDBUS_IMAGE="${OPENFDD_FIELDBUS_IMAGE:-ghcr.io/bbartling/openfdd-fieldbus:${tag}}"
  export OPENFDD_MQTT_IMAGE="${OPENFDD_MQTT_IMAGE:-ghcr.io/bbartling/openfdd-mqtt:${tag}}"
  export OPENFDD_MCP_IMAGE="${OPENFDD_MCP_IMAGE:-ghcr.io/bbartling/openfdd-mcp:${tag}}"
}

openfdd_stack_wait_health() {
  local base="${OPENFDD_API_BASE:-http://127.0.0.1:8080}"
  local timeout="${OPENFDD_HEALTH_TIMEOUT_SECS:-90}"
  local deadline=$((SECONDS + timeout))
  until curl -fsS "${base}/api/health" >/dev/null 2>&1; do
    if (( SECONDS >= deadline )); then
      echo "ERROR: central not healthy at ${base}/api/health after ${timeout}s" >&2
      return 1
    fi
    sleep 2
  done
  echo "OK health: ${base}/api/health"
}
