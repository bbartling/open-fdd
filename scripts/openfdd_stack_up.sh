#!/usr/bin/env bash
# Bring up an Open-FDD compose build recipe (pull or build).
#
#   ./scripts/openfdd_stack_up.sh standalone
#   ./scripts/openfdd_stack_up.sh csv --build
#   OPENFDD_IMAGE_TAG=sha-abc1234 ./scripts/openfdd_stack_up.sh central
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
    standalone|central|edge|csv) RECIPE="$1"; shift ;;
    --build) DO_BUILD=1; DO_PULL=0; shift ;;
    --no-pull) DO_PULL=0; shift ;;
    --pull) DO_PULL=1; shift ;;
    -h|--help)
      cat <<'EOF'
Usage: openfdd_stack_up.sh [standalone|central|edge|csv] [--build|--no-pull]

Recipes:
  standalone  mqtt + central + ui + fieldbus
  central     mqtt + central + ui
  edge        fieldbus only (needs OPENFDD_MQTT_HOST)
  csv         central + ui only (no mqtt/fieldbus)

Env: OPENFDD_IMAGE_TAG, OPENFDD_*_IMAGE, OPENFDD_JWT_SECRET, OPENFDD_ADMIN_PASSWORD
EOF
      exit 0
      ;;
    *) EXTRA+=("$1"); shift ;;
  esac
done

COMPOSE="$(openfdd_stack_recipe_file "$RECIPE")"
[[ -f "$COMPOSE" ]] || { echo "ERROR: missing $COMPOSE" >&2; exit 1; }
openfdd_stack_export_image_env
cd "$ROOT"

if [[ "$DO_PULL" -eq 1 ]]; then
  "$ROOT/scripts/openfdd_stack_pull.sh" "$RECIPE"
fi

ARGS=(-f "$COMPOSE")
if [[ "$DO_BUILD" -eq 1 ]]; then
  docker compose "${ARGS[@]}" up -d --build --remove-orphans "${EXTRA[@]+"${EXTRA[@]}"}"
else
  docker compose "${ARGS[@]}" up -d --remove-orphans "${EXTRA[@]+"${EXTRA[@]}"}"
fi

if [[ "$RECIPE" != "edge" ]]; then
  openfdd_stack_wait_health
  echo "UI: http://127.0.0.1:3000  API: ${OPENFDD_API_BASE:-http://127.0.0.1:8080}"
fi
echo "OK recipe=${RECIPE} up"
