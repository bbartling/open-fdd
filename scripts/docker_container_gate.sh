#!/usr/bin/env bash
# Shared Docker gate: crash/restart loops and startup import failures.
#
#   source scripts/docker_container_gate.sh
#   docker_gate_check_cid bridge "$cid"
#
#   docker_gate_check_compose docker/compose.dev.yml bridge commission mcp-rag
set -euo pipefail

DOCKER_GATE_MAX_RESTARTS="${DOCKER_GATE_MAX_RESTARTS:-5}"
DOCKER_GATE_LOG_SINCE="${DOCKER_GATE_LOG_SINCE:-15m}"

docker_gate_log_ok() { printf '  OK   %s\n' "$*"; }
docker_gate_log_fail() { printf '  FAIL %s\n' "$*" >&2; DOCKER_GATE_FAILURES=$((DOCKER_GATE_FAILURES + 1)); }

docker_gate_reset_failures() { DOCKER_GATE_FAILURES=0; }

docker_gate_log_since() {
  local cid="$1"
  local since="${2:-}"
  if [[ -n "$since" ]]; then
    printf '%s' "$since"
    return 0
  fi
  docker inspect -f '{{.State.StartedAt}}' "$cid" 2>/dev/null || printf '%s' "$DOCKER_GATE_LOG_SINCE"
}

docker_gate_critical_log_lines() {
  local cid="$1"
  local since="${2:-}"
  since="$(docker_gate_log_since "$cid" "$since")"
  docker logs --since "$since" "$cid" 2>&1 \
    | grep -Ei 'ModuleNotFoundError|ImportError:.*No module named|No module named |CRITICAL|Application startup failed' \
    | grep -v '404 Not Found' \
    | grep -v 'unknown-property' \
    | grep -v 'read-property-multiple' \
    | grep -v 'Connection reset by peer' \
    | grep -v 'CancelledError' \
    | grep -v 'KeyboardInterrupt' \
    | tail -5 \
    || true
}

docker_gate_check_cid() {
  local label="$1"
  local cid="$2"
  local since="${3:-$DOCKER_GATE_LOG_SINCE}"

  if [[ -z "$cid" ]]; then
    docker_gate_log_fail "Docker ${label}: no container id"
    return 1
  fi

  local status restart_count
  status="$(docker inspect -f '{{.State.Status}}' "$cid" 2>/dev/null || echo missing)"
  restart_count="$(docker inspect -f '{{.RestartCount}}' "$cid" 2>/dev/null || echo 0)"

  if [[ "$status" == "restarting" ]]; then
    docker_gate_log_fail "Docker ${label} (${cid:0:12}): crash loop (status=restarting, RestartCount=${restart_count})"
  elif [[ "$status" != "running" ]]; then
    docker_gate_log_fail "Docker ${label} (${cid:0:12}): not running (status=${status}, RestartCount=${restart_count})"
  elif [[ "${restart_count:-0}" -gt "$DOCKER_GATE_MAX_RESTARTS" ]]; then
    docker_gate_log_fail "Docker ${label} (${cid:0:12}): high restart count (${restart_count} > ${DOCKER_GATE_MAX_RESTARTS})"
  else
    docker_gate_log_ok "Docker ${label} running (RestartCount=${restart_count}, cid ${cid:0:12})"
  fi

  local crit
  crit="$(docker_gate_critical_log_lines "$cid" "$since")"
  if [[ -n "$crit" ]]; then
    docker_gate_log_fail "Docker ${label} (${cid:0:12}) startup/import errors: ${crit//$'\n' | }"
  else
    docker_gate_log_ok "Docker ${label} logs clean (${since}, cid ${cid:0:12})"
  fi
}

docker_gate_bridge_import_smoke() {
  local cid="$1"
  if [[ -z "$cid" ]]; then
    docker_gate_log_fail "bridge import smoke: no container id"
    return 1
  fi
  if docker exec "$cid" python3 -c \
    'from open_fdd.arrow_runtime.column_map_from_model import build_column_map_from_model_points' \
    >/dev/null 2>&1; then
    docker_gate_log_ok "bridge image has open_fdd.arrow_runtime.column_map_from_model"
  else
    docker_gate_log_fail "bridge image missing open_fdd.arrow_runtime.column_map_from_model — rebuild: ./scripts/docker_build.sh"
  fi
}

docker_gate_check_compose() {
  local compose_file="$1"
  shift
  local svc cid
  for svc in "$@"; do
    cid="$(docker compose -f "$compose_file" ps -q "$svc" 2>/dev/null || true)"
    docker_gate_check_cid "$svc" "$cid"
    if [[ "$svc" == "bridge" && -n "$cid" ]]; then
      docker_gate_bridge_import_smoke "$cid"
    fi
  done
}
