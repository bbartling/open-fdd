#!/usr/bin/env bash
# Open-FDD Supervisor — local dev stack (supervisor brings up addons).
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
if [[ -f docker/compose.bench.yml ]]; then
  COMPOSE+=(-f docker/compose.bench.yml)
fi
PROD_TAG="${OPENFDD_IMAGE_TAG:-latest}"
PROD_COMPOSE=("${COMPOSE[@]}" -f docker/compose.prod.yml)
PROFILES=()
if [[ "${OPENFDD_COMPOSE_PROFILES:-ai}" == *ai* ]]; then
  PROFILES+=(--profile ai)
fi
ACTION="${1:-up}"
HEALTH_URL="${OPENFDD_HEALTH_URL:-http://127.0.0.1:8765/health}"
HEALTH_DEADLINE_SEC="${OPENFDD_HEALTH_DEADLINE_SEC:-90}"
RUN_FULL_HEALTH="${OPENFDD_STACK_FULL_HEALTH:-1}"

wait_for_health() {
  local start now
  start=$(date +%s)
  while true; do
    if curl -sf --connect-timeout 2 --max-time 5 "$HEALTH_URL" | head -c 400; then
      echo
      return 0
    fi
    now=$(date +%s)
    if (( now - start >= HEALTH_DEADLINE_SEC )); then
      echo "Health check timed out after ${HEALTH_DEADLINE_SEC}s: $HEALTH_URL" >&2
      return 1
    fi
    sleep 2
  done
}

case "$ACTION" in
  up)
    ./scripts/run_local.sh stop 2>/dev/null || true
    "${COMPOSE[@]}" down 2>/dev/null || true
    if ! docker image inspect openfdd-bridge:local >/dev/null 2>&1; then
      ./scripts/docker_build.sh
    fi
    "${COMPOSE[@]}" "${PROFILES[@]}" up -d
    wait_for_health
    if [[ "$RUN_FULL_HEALTH" == 1 ]] && [[ -x "${ROOT}/scripts/stack_health_check.sh" ]]; then
      OPENFDD_BASE_URL="${OPENFDD_BASE_URL:-http://127.0.0.1:8765}" \
        "${ROOT}/scripts/stack_health_check.sh"
    fi
    echo "Supervisor stack up (openfdd-dev). Caddy optional: ./scripts/run_local.sh start caddy"
    ;;
  down)
    "${COMPOSE[@]}" down
    ;;
  health)
    wait_for_health
    ;;
  rebuild)
    ./scripts/run_local.sh stop 2>/dev/null || true
    ./scripts/docker_build.sh
    "${COMPOSE[@]}" "${PROFILES[@]}" up -d --force-recreate
    wait_for_health
    if [[ "$RUN_FULL_HEALTH" == 1 ]] && [[ -x "${ROOT}/scripts/stack_health_check.sh" ]]; then
      OPENFDD_BASE_URL="${OPENFDD_BASE_URL:-http://127.0.0.1:8765}" \
        "${ROOT}/scripts/stack_health_check.sh"
    fi
    ;;
  prod)
    ./scripts/run_local.sh stop 2>/dev/null || true
    export OPENFDD_IMAGE_TAG="${PROD_TAG}"
    echo "==> Pull GHCR production images (tag ${OPENFDD_IMAGE_TAG})"
    docker pull "ghcr.io/bbartling/openfdd-bridge:${OPENFDD_IMAGE_TAG}"
    docker pull "ghcr.io/bbartling/openfdd-commission:${OPENFDD_IMAGE_TAG}"
    docker pull "ghcr.io/bbartling/openfdd-mcp-rag:${OPENFDD_IMAGE_TAG}"
    "${PROD_COMPOSE[@]}" "${PROFILES[@]}" up -d --force-recreate --pull always
    wait_for_health
    chmod +x "${ROOT}/scripts/start_caddy_front.sh"
    "${ROOT}/scripts/start_caddy_front.sh" || true
    LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
    echo ""
    echo "Production stack (GHCR ${OPENFDD_IMAGE_TAG}) — OWASP ZAP targets from your LAN:"
    echo "  Primary (edge-like):  http://${LAN_IP}/"
    echo "  Direct bridge (dev):  http://${LAN_IP}:8765/  (if firewall allows)"
    echo "  Login API:            POST http://${LAN_IP}/api/auth/login"
    echo "  Health:               curl -sf http://${LAN_IP}/health"
    if [[ "$RUN_FULL_HEALTH" == 1 ]] && [[ -x "${ROOT}/scripts/stack_health_check.sh" ]]; then
      OPENFDD_BASE_URL="${OPENFDD_BASE_URL:-http://127.0.0.1:8765}" \
        "${ROOT}/scripts/stack_health_check.sh"
    fi
    ;;
  -h|--help)
    sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
    ;;
  *)
    echo "Unknown action: $ACTION (up|down|health|rebuild|prod)" >&2
    exit 1
    ;;
esac
