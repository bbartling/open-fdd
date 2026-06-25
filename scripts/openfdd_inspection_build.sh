#!/usr/bin/env bash
# Local UI inspection build — Rust edge + React dashboard + Docker, no long validation.
#
#   ./scripts/openfdd_inspection_build.sh              # start stack (build image if needed)
#   ./scripts/openfdd_inspection_build.sh --build      # rebuild dashboard + docker image
#   ./scripts/openfdd_inspection_build.sh --smoke      # also run auth + UI API smoke
#   ./scripts/openfdd_inspection_build.sh --desktop    # JSON/CSV-only (BACnet/Modbus off)
#
# Prefer one command: ./scripts/openfdd_start.sh
#
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_rust_site_lib.sh
source "$ROOT/scripts/openfdd_rust_site_lib.sh"
# shellcheck source=scripts/openfdd_bench_lib.sh
source "$ROOT/scripts/openfdd_bench_lib.sh"
openfdd_bench_load_env "$ROOT"

BUILD=0
SMOKE=0
DESKTOP=0
SKIP_RUST=0
PUBLIC_URL="${OPENFDD_PUBLIC_BASE_URL:-}"
BIND_HOST="${OPENFDD_BIND_HOST:-}"
COMPOSE_FILE="${COMPOSE_FILE:-$ROOT/docker-compose.local.yml}"
BASE="${OPENFDD_BRIDGE_BASE:-http://127.0.0.1:8080}"

usage() {
  cat <<'EOF'
Usage: scripts/openfdd_inspection_build.sh [--build] [--smoke] [--desktop] [--skip-rust] [--public-url URL]

Prepares auth, builds the React dashboard, starts Docker, waits for health, prints UI URL.
Does NOT run 1-hour or 6-hour validation.

  --build       npm run build + docker image build (local Dockerfile.local)
  --smoke       Run scripts/openfdd_auth_smoke.sh and scripts/openfdd_ui_smoke.sh
  --desktop     Use GHCR compose with JSON/CSV-only profile (BACnet/Modbus disabled)
  --skip-rust   Skip optional host cargo build (Docker image still includes Rust edge)
  --public-url  Remote inspection URL (also OPENFDD_PUBLIC_BASE_URL)

Env:
  OPENFDD_BIND_HOST=0.0.0.0   bind edge to all interfaces for LAN inspection
  OPENFDD_PUBLIC_BASE_URL     printed remote UI URL for another computer
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --build) BUILD=1 ;;
    --smoke) SMOKE=1 ;;
    --desktop) DESKTOP=1 ;;
    --skip-rust) SKIP_RUST=1 ;;
    --public-url)
      PUBLIC_URL="${2:?--public-url requires value}"
      shift
      ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

if [[ -n "$PUBLIC_URL" ]]; then
  BASE="$PUBLIC_URL"
  export OPENFDD_BRIDGE_BASE="$BASE"
fi
if [[ -n "$BIND_HOST" ]]; then
  export OPENFDD_BIND_HOST="$BIND_HOST"
  export PORT="${OPENFDD_PORT:-8080}"
fi

# Explicit --build overrides bench.env.local (inspection/dev intent).
if [[ "$BUILD" == "1" ]]; then
  export OPENFDD_ALLOW_LOCAL_BUILD=1
fi

AUTH="$ROOT/workspace/auth.env.local"
BOOTSTRAP="$ROOT/workspace/bootstrap_credentials.once.txt"

mkdir -p "$ROOT/workspace/logs"

if [[ ! -f "$AUTH" ]]; then
  echo "==> Generating $AUTH (plaintext shown once)"
  "$ROOT/scripts/openfdd_auth_init.sh" --show-secrets --restart || \
    "$ROOT/scripts/openfdd_auth_init.sh" --show-secrets
  echo "==> Save passwords from above or from $BOOTSTRAP (gitignored), then delete the handoff file when done."
elif [[ ! -f "$BOOTSTRAP" ]]; then
  echo "==> No bootstrap handoff — rotating credentials (plaintext shown once)"
  "$ROOT/scripts/openfdd_auth_init.sh" --rotate --all --show-secrets --restart
fi

echo "==> Building React dashboard"
if [[ -d "$ROOT/workspace/dashboard/node_modules" ]]; then
  (cd "$ROOT/workspace/dashboard" && npm run build)
else
  (cd "$ROOT/workspace/dashboard" && npm ci && npm run build)
fi

if [[ "$SKIP_RUST" != "1" ]] && command -v cargo >/dev/null 2>&1; then
  echo "==> Host cargo build (optional sanity check)"
  openfdd_bench_require_free_disk_gb 6
  (cd "$ROOT/edge" && cargo build --workspace)
fi

export OPENFDD_COMPOSE_ROOT="$ROOT"
export OPENFDD_RUN_UID="${OPENFDD_RUN_UID:-$(id -u)}"
export OPENFDD_RUN_GID="${OPENFDD_RUN_GID:-$(id -g)}"

if [[ "$DESKTOP" == "1" ]]; then
  echo "==> Starting desktop JSON/CSV inspection profile (GHCR compose)"
  export OPENFDD_BACNET_ENABLED=0
  export OPENFDD_MODBUS_ENABLED=0
  export OPENFDD_HAYSTACK_ENABLED=0
  export OPENFDD_JSON_API_ENABLED=1
  export OPENFDD_IMPORT_ENABLED=1
  export OPENFDD_EXPORT_ENABLED=1
  if [[ "$BUILD" == "1" ]]; then
    docker compose -f "$ROOT/docker/compose.edge.rust.yml" \
      -f "$ROOT/docker/compose.desktop.json-csv.yml" \
      --profile desktop-json-csv up -d --build
  else
    docker compose -f "$ROOT/docker/compose.edge.rust.yml" \
      -f "$ROOT/docker/compose.desktop.json-csv.yml" \
      --profile desktop-json-csv up -d
  fi
else
  echo "==> Starting local bridge (docker-compose.local.yml)"
  if [[ "$BUILD" == "1" ]]; then
    openfdd_bench_require_local_build_allowed 12
    "$ROOT/scripts/openfdd_local_up.sh" --build
  else
    "$ROOT/scripts/openfdd_local_up.sh"
  fi
fi

echo "==> Waiting for health at $BASE"
for i in $(seq 1 45); do
  if curl -fsS "$BASE/health" >/dev/null 2>&1 && curl -fsS "$BASE/api/health" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
curl -fsS "$BASE/api/health" | head -c 400
echo

if [[ "$SMOKE" == "1" ]]; then
  echo "==> Auth smoke"
  OPENFDD_BRIDGE_BASE="$BASE" "$ROOT/scripts/openfdd_auth_smoke.sh"
  echo "==> Login smoke (all roles)"
  OPENFDD_BRIDGE_BASE="$BASE" "$ROOT/scripts/openfdd_login_ui_smoke.sh"
  echo "==> UI smoke"
  OPENFDD_API_BASE="$BASE" "$ROOT/scripts/openfdd_ui_smoke.sh" --base-url "$BASE"
fi

echo ""
echo "Open-FDD local UI:"
echo "  http://127.0.0.1:${OPENFDD_PORT:-8080}"
if [[ -n "$PUBLIC_URL" ]]; then
  echo ""
  echo "Open-FDD remote UI:"
  echo "  $PUBLIC_URL"
fi
echo ""
echo "Credentials (plaintext — NOT the bcrypt hash in auth.env.local):"
if [[ -f "$BOOTSTRAP" ]]; then
  echo "  $BOOTSTRAP"
else
  echo "  (missing — rotate with ./scripts/openfdd_auth_init.sh --rotate --all --show-secrets)"
fi
echo ""
echo "Login users: operator, integrator, agent"
echo "Tabs to click: / /login /bacnet /modbus /haystack /json-api /model /sql-fdd /plot /reports /exports /host /data-management"
echo ""
if [[ "$DESKTOP" == "1" ]]; then
  echo "Stop stack:"
  echo "  docker compose -f docker/compose.edge.rust.yml -f docker/compose.desktop.json-csv.yml --profile desktop-json-csv down"
else
  echo "Stop stack:"
  echo "  docker compose -f docker-compose.local.yml down"
fi
echo ""
if [[ -f "$ROOT/docker/caddy/Caddyfile" ]] && docker ps --format '{{.Names}}' 2>/dev/null | grep -q openfdd-caddy; then
  echo "Caddy:"
  echo "  http://localhost"
  echo "  https://localhost  (curl -k https://localhost/health)"
fi
