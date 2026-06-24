#!/usr/bin/env bash
# Safe local Open-FDD startup for small hosts (8 GB RAM).
# Logs to workspace/logs/local-up.log — inspect there if SSH drops during --build.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

LOG_DIR="$ROOT/workspace/logs"
LOG_FILE="$LOG_DIR/local-up.log"
mkdir -p "$LOG_DIR"

exec > >(tee -a "$LOG_FILE") 2>&1

echo "==> openfdd_local_up.sh $(date -Is) pid=$$"

BUILD=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --build) BUILD=1 ;;
    --help|-h)
      cat <<'EOF'
Usage: scripts/openfdd_local_up.sh [--build]

Starts openfdd-bridge only using docker-compose.local.yml (no GHCR, no npm-in-docker).

  --build   Rebuild image with Dockerfile.local (memory-limited; can take 15–40 min on 8 GB)

Without --build, reuses image open-fdd-openfdd-bridge:local if present.

UI: http://127.0.0.1:8080
Log: workspace/logs/local-up.log

Avoid: docker compose up --build (root docker-compose.yml) on RAM-constrained hosts —
that path runs npm + full release rustc and can OOM the machine.
EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
  esac
  shift
done

if [[ ! -f "$ROOT/workspace/auth.env.local" ]]; then
  echo "ERROR: missing workspace/auth.env.local"
  echo "Create one or copy from workspace/auth.env.example"
  exit 1
fi

need_frontend_build=0
if [[ ! -f "$ROOT/frontend/index.html" ]]; then
  need_frontend_build=1
elif [[ ! -d "$ROOT/frontend/assets" ]]; then
  need_frontend_build=1
else
  asset_count="$(find "$ROOT/frontend/assets" -mindepth 1 -maxdepth 1 2>/dev/null | wc -l | tr -d ' ')"
  if [[ "${asset_count:-0}" -eq 0 ]]; then
    need_frontend_build=1
  fi
fi

if [[ "$need_frontend_build" -eq 1 ]]; then
  echo "WARN: frontend build missing — running npm run build in workspace/dashboard"
  if command -v npm >/dev/null 2>&1; then
    (cd "$ROOT/workspace/dashboard" && npm ci && npm run build)
  else
    echo "ERROR: npm not found and frontend/ not built. Install node or run npm run build in workspace/dashboard"
    exit 1
  fi
fi

AVAIL_KB="$(awk '/MemAvailable:/ {print $2}' /proc/meminfo)"
AVAIL_MB=$((AVAIL_KB / 1024))
echo "==> MemAvailable: ${AVAIL_MB} MB"

if [[ "$BUILD" -eq 1 && "$AVAIL_MB" -lt 2048 ]]; then
  echo "WARN: less than 2 GB free — release build may OOM. Close other apps or add swap."
  echo "      Continuing in 10s (Ctrl-C to abort)…"
  sleep 10
fi

export OPENFDD_CARGO_BUILD_JOBS="${OPENFDD_CARGO_BUILD_JOBS:-1}"
export OPENFDD_RUN_UID="${OPENFDD_RUN_UID:-$(id -u)}"
export OPENFDD_RUN_GID="${OPENFDD_RUN_GID:-$(id -g)}"
export COMPOSE_FILE="$ROOT/docker-compose.local.yml"

build_local_image() {
  local build_args=(
    --build-arg "CARGO_BUILD_JOBS=${OPENFDD_CARGO_BUILD_JOBS}"
    -f "$ROOT/Dockerfile.local"
    -t open-fdd-openfdd-bridge:local
    "$ROOT"
  )

  if docker buildx version >/dev/null 2>&1; then
    echo "==> Using BuildKit (buildx) with 3g build memory cap"
    export DOCKER_BUILDKIT=1
    docker build --progress=plain --memory=3g --memory-swap=5g "${build_args[@]}"
  else
    echo "==> buildx not installed — using legacy docker build (DOCKER_BUILDKIT=0)"
    echo "    Install docker-buildx for build memory limits: sudo apt install docker-buildx-plugin"
    export DOCKER_BUILDKIT=0
    docker build "${build_args[@]}"
  fi
}

if [[ "$BUILD" -eq 1 ]]; then
  echo "==> Building open-fdd-openfdd-bridge:local (jobs=${OPENFDD_CARGO_BUILD_JOBS}, log appended here)"
  build_local_image
  echo "==> Docker build finished"
elif docker image inspect open-fdd-openfdd-bridge:latest >/dev/null 2>&1; then
  echo "==> Tagging existing open-fdd-openfdd-bridge:latest as :local (no rebuild)"
  docker tag open-fdd-openfdd-bridge:latest open-fdd-openfdd-bridge:local
elif ! docker image inspect open-fdd-openfdd-bridge:local >/dev/null 2>&1; then
  echo "==> No local image — run with --build once: ./scripts/openfdd_local_up.sh --build"
  exit 1
fi

if [[ "$BUILD" -eq 0 ]] && curl -fsS http://127.0.0.1:8080/api/health >/dev/null 2>&1; then
  echo "==> Bridge already healthy on :8080 — open http://127.0.0.1:8080"
  curl -fsS http://127.0.0.1:8080/api/health
  echo
  exit 0
fi

if docker ps -a --format '{{.Names}}' | grep -qx openfdd-bridge; then
  echo "==> Replacing existing openfdd-bridge container (switching to local compose)"
  docker stop openfdd-bridge >/dev/null 2>&1 || true
  docker rm openfdd-bridge >/dev/null 2>&1 || true
fi

echo "==> Starting openfdd-bridge (compose local)"
docker compose -f "$ROOT/docker-compose.local.yml" up -d --no-build openfdd-bridge

for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8080/api/health >/dev/null 2>&1; then
    echo "==> Health OK — open http://127.0.0.1:8080"
    curl -fsS http://127.0.0.1:8080/api/health
    echo
    exit 0
  fi
  sleep 2
done

echo "ERROR: bridge did not become healthy — check: docker compose -f docker-compose.local.yml logs openfdd-bridge"
exit 1
