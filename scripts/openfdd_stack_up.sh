#!/usr/bin/env bash
# Bring up an Open-FDD compose build recipe (pull or build).
#
#   ./scripts/openfdd_stack_up.sh standalone
#   ./scripts/openfdd_stack_up.sh react-ot
#   OPENFDD_IMAGE_TAG=sha-abc1234 ./scripts/openfdd_stack_up.sh react-ot
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_stack_lib.sh
source "$ROOT/scripts/openfdd_stack_lib.sh"

RECIPE="standalone"
DO_BUILD=0
DO_PULL=1
EXTRA=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    standalone|central|edge|csv|react|react-ot) RECIPE="$1"; shift ;;
    --build) DO_BUILD=1; DO_PULL=0; shift ;;
    --no-pull) DO_PULL=0; shift ;;
    --pull) DO_PULL=1; shift ;;
    -h|--help)
      cat <<'EOF'
Usage: openfdd_stack_up.sh [standalone|central|edge|csv|react|react-ot] [--build|--no-pull] [--caddy]

Recipes:
  standalone  mqtt + central + streamlit-legacy ui + fieldbus
  central     mqtt + central + streamlit-legacy ui
  edge        fieldbus only (needs OPENFDD_MQTT_HOST)
  csv         central + streamlit-legacy ui only
  react       mqtt + central + React web (no fieldbus)
  react-ot    mqtt + central + React web + fieldbus (OT bench)

Options:
  --caddy     Also start Caddy on :80 → UI (/api* → central)
  --wattlab   Mount WattLab /data + vibe20 PYTHONPATH (compose.wattlab.yml)

Env: OPENFDD_IMAGE_TAG, OPENFDD_*_IMAGE, OPENFDD_JWT_SECRET, OPENFDD_ADMIN_PASSWORD
     OPENFDD_CADDY=1 (same as --caddy), OPENFDD_CENTRAL_BIND=127.0.0.1 (LAN via Caddy)
     OPENFDD_WATTLAB=1 (same as --wattlab), OPENFDD_WATTLAB_HOST_WORKSPACE, OPENFDD_WATTLAB_HOST_SRC
EOF
      exit 0
      ;;
    --caddy) export OPENFDD_CADDY=1; shift ;;
    --wattlab) export OPENFDD_WATTLAB=1; shift ;;
    *) EXTRA+=("$1"); shift ;;
  esac
done

mapfile -t ARGS < <(openfdd_stack_compose_args "$RECIPE")
[[ ${#ARGS[@]} -ge 2 ]] || { echo "ERROR: no compose files for recipe=$RECIPE" >&2; exit 1; }
openfdd_stack_export_image_env
cd "$ROOT"

if [[ "$DO_PULL" -eq 1 ]]; then
  "$ROOT/scripts/openfdd_stack_pull.sh" "$RECIPE"
fi

if [[ "${OPENFDD_CADDY:-0}" == "1" || "${OPENFDD_CADDY:-}" == "true" ]]; then
  if [[ "$RECIPE" == "edge" ]]; then
    echo "WARN: --caddy ignored for edge recipe (no UI)" >&2
  else
    ARGS+=(-f "$ROOT/docker/compose.caddy.yml")
  fi
fi
if [[ "${OPENFDD_WATTLAB:-0}" == "1" || "${OPENFDD_WATTLAB:-}" == "true" ]]; then
  if [[ "$RECIPE" == "edge" ]]; then
    echo "WARN: --wattlab ignored for edge recipe (no UI)" >&2
  else
    ARGS+=(-f "$ROOT/docker/compose.wattlab.yml")
  fi
fi

# React SPA image is often compose-build until GHCR publishes openfdd-web.
# Never `--build` the whole stack (would rebuild Rust from local Dockerfiles).
if [[ "$RECIPE" == "react" || "$RECIPE" == "react-ot" ]]; then
  if [[ "$DO_BUILD" -eq 1 ]] || ! docker image inspect "$OPENFDD_WEB_IMAGE" >/dev/null 2>&1; then
    echo "NOTE: building openfdd-web locally (image not present or --build): $OPENFDD_WEB_IMAGE"
    docker compose "${ARGS[@]}" build web
  fi
fi

if [[ "$DO_BUILD" -eq 1 && "$RECIPE" != "react" && "$RECIPE" != "react-ot" ]]; then
  docker compose "${ARGS[@]}" up -d --build --remove-orphans "${EXTRA[@]+"${EXTRA[@]}"}"
else
  docker compose "${ARGS[@]}" up -d --remove-orphans "${EXTRA[@]+"${EXTRA[@]}"}"
fi

if [[ "$RECIPE" != "edge" ]]; then
  openfdd_stack_wait_health
  echo "UI: http://127.0.0.1:3000  API: ${OPENFDD_API_BASE:-http://127.0.0.1:8080}"
  if [[ "$RECIPE" == "react-ot" ]]; then
    echo "Fieldbus: http://127.0.0.1:8081"
  fi
  if [[ "${OPENFDD_CADDY:-0}" == "1" || "${OPENFDD_CADDY:-}" == "true" ]]; then
    echo "Caddy: http://<host>/  (UI)  http://<host>/api/health  (central)"
  fi
  if [[ "${OPENFDD_WATTLAB:-0}" == "1" || "${OPENFDD_WATTLAB:-}" == "true" ]]; then
    echo "WattLab: WATTLAB_STUDIO_WORKSPACE=/data (host ${OPENFDD_WATTLAB_HOST_WORKSPACE:-~/wattlab_workspace})"
  fi
fi
echo "OK recipe=${RECIPE} up"
