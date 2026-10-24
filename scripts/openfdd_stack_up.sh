#!/usr/bin/env bash
# Bring up an Open-FDD compose build recipe (pull or build).
#
#   ./scripts/openfdd_stack_up.sh portal
#   ./scripts/openfdd_stack_up.sh csv
#   OPENFDD_IMAGE_TAG=sha-abc1234 ./scripts/openfdd_stack_up.sh portal
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_stack_lib.sh
source "$ROOT/scripts/openfdd_stack_lib.sh"

RECIPE="portal"
DO_BUILD=0
DO_PULL=1
EXTRA=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    portal|standalone|central|edge|csv|react|react-ot) RECIPE="$1"; shift ;;
    --build) DO_BUILD=1; DO_PULL=0; shift ;;
    --no-pull) DO_PULL=0; shift ;;
    --pull) DO_PULL=1; shift ;;
    -h|--help)
      cat <<'EOF'
Usage: openfdd_stack_up.sh [portal|standalone|central|edge|csv|react|react-ot] [--build|--no-pull] [--caddy]

Recipes:
  portal      4.0 default: central + React web + Timescale (no MQTT, no fieldbus)
  central     archived OT mqtt + central (no fieldbus)
  csv         central + React web (openfdd-web)
  react       archived OT: mqtt + central + React web (no fieldbus)

Fieldbus recipes (standalone, edge, react-ot) are refused. Render the pinned
archive lane instead:
  OPENFDD_OT_ARCHIVE_RESTORE=1 ./archive/ot-edge/unqualified-cdaa4f15/recipes/restore-isolated.sh --replay

Options:
  --caddy     Start Caddy on :80 → web (/api* → central). Default ON for react/react-ot;
              use OPENFDD_CADDY=0 to disable. Requires a recipe that includes the web service.
  --wattlab   Mount WattLab workspace onto central (compose.wattlab.react.yml)

Env: OPENFDD_IMAGE_TAG, OPENFDD_*_IMAGE, OPENFDD_JWT_SECRET, OPENFDD_ADMIN_PASSWORD
     OPENFDD_CADDY=1|0, OPENFDD_CENTRAL_BIND=127.0.0.1 (LAN via Caddy)
     OPENFDD_WATTLAB=1 (same as --wattlab), OPENFDD_WATTLAB_HOST_WORKSPACE, OPENFDD_WATTLAB_HOST_SRC
EOF
      exit 0
      ;;
    --caddy) export OPENFDD_CADDY=1; shift ;;
    --wattlab) export OPENFDD_WATTLAB=1; shift ;;
    *) EXTRA+=("$1"); shift ;;
  esac
done

case "$RECIPE" in
  standalone|edge|react-ot)
    echo "4.0 does not start fieldbus (recipe=$RECIPE)." >&2
    echo "Render the pinned OT archive lane (no containers):" >&2
    echo "  OPENFDD_OT_ARCHIVE_RESTORE=1 ./archive/ot-edge/unqualified-cdaa4f15/recipes/restore-isolated.sh --replay" >&2
    exit 2
    ;;
esac

# React product recipes: Caddy :80 is the default LAN ingress (blank-/login class bugs).
if [[ "$RECIPE" == "portal" || "$RECIPE" == "react" || "$RECIPE" == "react-ot" ]]; then
  if [[ -z "${OPENFDD_CADDY+x}" ]]; then
    export OPENFDD_CADDY=1
  fi
  if [[ -z "${OPENFDD_JWT_SECRET:-}" && -f "$ROOT/.env" ]]; then
    # shellcheck disable=SC1091
    set -a && source "$ROOT/.env" && set +a
  fi
  if [[ -z "${OPENFDD_JWT_SECRET:-}" ]]; then
    echo "ERROR: Set OPENFDD_JWT_SECRET in the environment or $ROOT/.env (unique per deployment)." >&2
    exit 1
  fi
fi

mapfile -t ARGS < <(openfdd_stack_compose_args "$RECIPE")
[[ ${#ARGS[@]} -ge 2 ]] || { echo "ERROR: no compose files for recipe=$RECIPE" >&2; exit 1; }
openfdd_stack_export_image_env
if [[ "$RECIPE" == "portal" || "$RECIPE" == "react" || "$RECIPE" == "react-ot" ]]; then
  openfdd_stack_guard_ghcr_web
fi
cd "$ROOT"

if [[ "$DO_PULL" -eq 1 ]]; then
  "$ROOT/scripts/openfdd_stack_pull.sh" "$RECIPE"
fi

if [[ "${OPENFDD_CADDY:-0}" == "1" || "${OPENFDD_CADDY:-}" == "true" ]]; then
  if [[ "$RECIPE" == "portal" || "$RECIPE" == "react" || "$RECIPE" == "react-ot" || "$RECIPE" == "csv" ]]; then
    ARGS+=(-f "$ROOT/docker/compose.caddy.react.yml")
  else
    echo "WARN: --caddy requires portal, react, react-ot, or csv (web service); ignored for recipe=$RECIPE" >&2
  fi
fi
if [[ "${OPENFDD_WATTLAB:-0}" == "1" || "${OPENFDD_WATTLAB:-}" == "true" ]]; then
  if [[ "$RECIPE" == "edge" ]]; then
    echo "WARN: --wattlab ignored for edge recipe" >&2
  else
    ARGS+=(-f "$ROOT/docker/compose.wattlab.react.yml")
  fi
fi

# React SPA image is often compose-build until GHCR publishes openfdd-web.
# Never `--build` the whole stack (would rebuild Rust from local Dockerfiles).
if [[ "$RECIPE" == "portal" || "$RECIPE" == "react" || "$RECIPE" == "react-ot" ]]; then
  if [[ "$DO_BUILD" -eq 1 ]] || ! docker image inspect "$OPENFDD_WEB_IMAGE" >/dev/null 2>&1; then
    echo "NOTE: building openfdd-web locally (image not present or --build): $OPENFDD_WEB_IMAGE"
    docker compose "${ARGS[@]}" build web
  fi
fi

# Data-safe: `up -d` reuses named volumes. This script never passes `-v` / `--volumes`.
echo "Data-safe update: compose up reuses named volumes (no down -v, no volume prune)."
if [[ "$DO_BUILD" -eq 1 && "$RECIPE" != "portal" && "$RECIPE" != "react" && "$RECIPE" != "react-ot" ]]; then
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
    echo "Caddy: http://<host>/  (UI)  http://<host>/auth  (login)  http://<host>/api/health"
  fi
  if [[ "${OPENFDD_WATTLAB:-0}" == "1" || "${OPENFDD_WATTLAB:-}" == "true" ]]; then
    echo "WattLab: WATTLAB_STUDIO_WORKSPACE=/data (host ${OPENFDD_WATTLAB_HOST_WORKSPACE:-~/wattlab_workspace})"
  fi
fi
echo "OK recipe=${RECIPE} up"
