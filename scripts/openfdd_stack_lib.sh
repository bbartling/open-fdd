#!/usr/bin/env bash
# Shared helpers for Open-FDD stack compose recipes (central/web/fieldbus/mqtt).
set -euo pipefail

openfdd_stack_root() {
  cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd
}

# Primary compose file for single-file recipes (legacy callers).
openfdd_stack_recipe_file() {
  local recipe="${1:-standalone}"
  local root
  root="$(openfdd_stack_root)"
  case "$recipe" in
    standalone) echo "$root/docker/compose.standalone.yml" ;;
    central) echo "$root/docker/compose.central.yml" ;;
    edge) echo "$root/docker/compose.edge.yml" ;;
    csv) echo "$root/docker/compose.csv.yml" ;;
    react|react-ot) echo "$root/docker/compose.react.yml" ;;
    *)
      echo "ERROR: unknown recipe '$recipe' (standalone|central|edge|csv|react|react-ot)" >&2
      return 2
      ;;
  esac
}

# Print docker compose -f args for a recipe (one path per line after each -f).
openfdd_stack_compose_args() {
  local recipe="${1:-standalone}"
  local root
  root="$(openfdd_stack_root)"
  case "$recipe" in
    standalone)
      printf '%s\n' -f "$root/docker/compose.standalone.yml"
      if [[ -f "$root/docker/compose.standalone.local.yml" ]]; then
        printf '%s\n' -f "$root/docker/compose.standalone.local.yml"
      fi
      ;;
    central)
      printf '%s\n' -f "$root/docker/compose.central.yml"
      ;;
    edge)
      printf '%s\n' -f "$root/docker/compose.edge.yml"
      ;;
    csv)
      printf '%s\n' -f "$root/docker/compose.csv.yml"
      ;;
    react)
      printf '%s\n' -f "$root/docker/compose.react.yml"
      ;;
    react-ot)
      printf '%s\n' -f "$root/docker/compose.react.yml"
      printf '%s\n' -f "$root/docker/compose.react.fieldbus.yml"
      local local_override="${OPENFDD_COMPOSE_LOCAL:-docker/compose.react.fieldbus.local.yml}"
      if [[ -f "$root/$local_override" ]]; then
        printf '%s\n' -f "$root/$local_override"
      elif [[ -f "$root/docker/compose.react.fieldbus.local.yml" ]]; then
        printf '%s\n' -f "$root/docker/compose.react.fieldbus.local.yml"
      fi
      ;;
    *)
      echo "ERROR: unknown recipe '$recipe'" >&2
      return 2
      ;;
  esac
}

openfdd_stack_images() {
  local tag="${OPENFDD_IMAGE_TAG:-nightly}"
  echo "ghcr.io/bbartling/openfdd-central:${tag}"
  echo "ghcr.io/bbartling/openfdd-web:${tag}"
  echo "ghcr.io/bbartling/openfdd-fieldbus:${tag}"
  echo "ghcr.io/bbartling/openfdd-mqtt:${tag}"
  echo "ghcr.io/bbartling/openfdd-mcp:${tag}"
  # Archive/oracle only — not required for react / react-ot product topology.
  echo "ghcr.io/bbartling/openfdd-ui:${tag}"
}

openfdd_stack_export_image_env() {
  local tag="${OPENFDD_IMAGE_TAG:-nightly}"
  export OPENFDD_CENTRAL_IMAGE="${OPENFDD_CENTRAL_IMAGE:-ghcr.io/bbartling/openfdd-central:${tag}}"
  export OPENFDD_UI_IMAGE="${OPENFDD_UI_IMAGE:-ghcr.io/bbartling/openfdd-ui:${tag}}"
  export OPENFDD_WEB_IMAGE="${OPENFDD_WEB_IMAGE:-ghcr.io/bbartling/openfdd-web:${tag}}"
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
