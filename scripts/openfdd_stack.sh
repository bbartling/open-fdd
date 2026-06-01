#!/usr/bin/env bash
# Open-FDD Supervisor — local dev stack (HA OS model: supervisor brings up addons).
#
#   ./scripts/openfdd_stack.sh up      # stop legacy systemd stack, compose up, health
#   ./scripts/openfdd_stack.sh down
#   ./scripts/openfdd_stack.sh health
#   ./scripts/openfdd_stack.sh rebuild # docker_build + up
#
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

COMPOSE=(docker compose -f docker/compose.dev.yml)
ACTION="${1:-up}"

health() {
  curl -sf "http://127.0.0.1:8765/health" | head -c 400
  echo
}

case "$ACTION" in
  up)
    ./scripts/run_local.sh stop 2>/dev/null || true
    "${COMPOSE[@]}" down 2>/dev/null || true
    if ! docker image inspect openfdd-bridge:local >/dev/null 2>&1; then
      ./scripts/docker_build.sh
    fi
    "${COMPOSE[@]}" up -d
    sleep 6
    health
    echo "Supervisor stack up (openfdd-dev). Caddy optional: ./scripts/run_local.sh start caddy"
    ;;
  down)
    "${COMPOSE[@]}" down
    ;;
  health)
    health
    ;;
  rebuild)
    ./scripts/run_local.sh stop 2>/dev/null || true
    ./scripts/docker_build.sh
    "${COMPOSE[@]}" up -d --force-recreate
    sleep 6
    health
    ;;
  -h|--help)
    sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
    ;;
  *)
    echo "Unknown action: $ACTION (up|down|health|rebuild)" >&2
    exit 1
    ;;
esac
