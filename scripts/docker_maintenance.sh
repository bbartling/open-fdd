#!/usr/bin/env bash
# Safe Docker maintenance for Open-FDD dev/edge — never prunes bind-mounted workspace data.
#
#   ./scripts/docker_maintenance.sh              # report + light cleanup
#   ./scripts/docker_maintenance.sh --prune      # remove dangling images/build cache
#   ./scripts/docker_maintenance.sh --rebuild    # rebuild local images after code changes
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

COMPOSE=(docker compose -f docker/compose.dev.yml -f docker/compose.bench.yml)
PRUNE=0
REBUILD=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --prune) PRUNE=1; shift ;;
    --rebuild) REBUILD=1; shift ;;
    -h|--help)
      sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown: $1" >&2; exit 1 ;;
  esac
done

echo "==> Open-FDD Docker maintenance"
docker system df 2>/dev/null || true

echo "==> Container status"
"${COMPOSE[@]}" ps -a 2>/dev/null || true

for svc in bridge commission mcp-rag ollama; do
  cid="$("${COMPOSE[@]}" ps -q "$svc" 2>/dev/null || true)"
  if [[ -n "$cid" ]]; then
    health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid" 2>/dev/null || echo unknown)"
    echo "  ${svc}: ${health}"
    err_count="$(docker logs --since 30m "$cid" 2>&1 | grep -ciE 'error|exception|traceback' || true)"
    if [[ "${err_count:-0}" -gt 0 ]]; then
      echo "    WARN ${err_count} error-like log lines (last 30m) — tail:"
      docker logs --tail 15 "$cid" 2>&1 | sed 's/^/      /' || true
    fi
  else
    echo "  ${svc}: not running"
  fi
done

if [[ "$PRUNE" == 1 ]]; then
  echo "==> Prune dangling images and build cache (NOT volumes — workspace is bind-mounted)"
  docker image prune -f 2>/dev/null || true
  docker builder prune -f --filter 'until=24h' 2>/dev/null || true
fi

if [[ "$REBUILD" == 1 ]]; then
  echo "==> Rebuild Open-FDD images"
  ./scripts/docker_build.sh
  "${COMPOSE[@]}" up -d --build bridge commission mcp-rag ollama
  sleep 6
fi

bridge_cid="$("${COMPOSE[@]}" ps -q bridge 2>/dev/null || true)"
if [[ -n "$bridge_cid" ]]; then
  echo "==> Feather compact (Arrow historian — deferred ingest shards)"
  if docker compose -f docker/compose.dev.yml -f docker/compose.bench.yml exec -T bridge \
    python -m openfdd_bridge.feather_store --compact 2>/dev/null; then
    echo "  feather compact via bridge container OK"
  else
    echo "  WARN feather compact in container failed — run on host if needed"
  fi
fi

echo "OK — docker maintenance complete"
