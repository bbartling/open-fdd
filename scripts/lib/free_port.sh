#!/usr/bin/env bash
# Stop any process listening on a TCP port (for local dev restarts).
# Usage: source scripts/lib/free_port.sh && free_port 8060 "RCx Central API"

_stop_rcx_central_docker_on_port() {
  local port="$1"
  command -v docker >/dev/null 2>&1 || return 0
  local root
  root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
  local compose="${root}/docker/rcx-central/docker-compose.yml"
  [[ -f "$compose" ]] || return 0

  local service=""
  case "$port" in
    8060) service="rcx-central-api" ;;
    8050) service="rcx-central-dash" ;;
    *) return 0 ;;
  esac

  if docker compose -f "$compose" ps --status running "$service" 2>/dev/null | grep -q "$service"; then
    echo "Stopping Docker ${service} on port ${port}..."
    docker compose -f "$compose" stop "$service" >/dev/null 2>&1 || true
    sleep 1
  fi
}

free_port() {
  local port="${1:?port required}"
  local label="${2:-listener}"
  local pids=""

  _stop_rcx_central_docker_on_port "$port"

  if command -v fuser >/dev/null 2>&1; then
    if ! fuser "${port}/tcp" >/dev/null 2>&1; then
      return 0
    fi
    echo "Port ${port} in use — stopping existing ${label}..."
    fuser -k "${port}/tcp" >/dev/null 2>&1 || true
    sleep 1
    if fuser "${port}/tcp" >/dev/null 2>&1; then
      fuser -k -KILL "${port}/tcp" >/dev/null 2>&1 || true
      sleep 0.5
    fi
    if fuser "${port}/tcp" >/dev/null 2>&1; then
      echo "Warning: port ${port} still busy after SIGKILL (Docker proxy? run: docker compose -f docker/rcx-central/docker-compose.yml down)" >&2
      return 1
    fi
    echo "Port ${port} free."
    return 0
  fi

  if command -v ss >/dev/null 2>&1; then
    pids=$(ss -tlnp "sport = :${port}" 2>/dev/null | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u || true)
  elif command -v lsof >/dev/null 2>&1; then
    pids=$(lsof -ti "tcp:${port}" -sTCP:LISTEN 2>/dev/null || true)
  fi

  if [[ -z "${pids}" ]]; then
    return 0
  fi

  echo "Port ${port} in use — stopping PID(s): ${pids} (${label})..."
  kill ${pids} 2>/dev/null || true
  sleep 1
  if ss -tlnp "sport = :${port}" >/dev/null 2>&1; then
    kill -9 ${pids} 2>/dev/null || true
  fi
}
