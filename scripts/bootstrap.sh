#!/bin/bash
#
# open-fdd bootstrap: full Docker stack (DB, Grafana, BACnet server, scraper, API).
#
# Usage:
#   ./scripts/bootstrap.sh            # Start full stack (builds all images)
#   ./scripts/bootstrap.sh --verify   # Check what's running
#   ./scripts/bootstrap.sh --minimal  # Raw BACnet only: DB + Grafana + BACnet server + scraper (no FDD, weather, API)
#   ./scripts/bootstrap.sh --build api   # Rebuild and restart only the API (e.g. after editing config UI static files)
#   ./scripts/bootstrap.sh --build api bacnet-scraper   # Rebuild and restart multiple services
#   ./scripts/bootstrap.sh --build-all  # Rebuild and restart all containers (no DB wait/migrations)
#   ./scripts/bootstrap.sh --reset-grafana  # Wipe Grafana volume (fix provisioning); restarts Grafana
#   ./scripts/bootstrap.sh --retention-days 180   # TimescaleDB retention (default 365)
#   ./scripts/bootstrap.sh --log-max-size 50m --log-max-files 2   # Docker log rotation (default 100m, 3)
#
# Prerequisite: diy-bacnet-server as sibling of open-fdd (for BACnet stack).
#

set -e
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PLATFORM_DIR="$REPO_ROOT/platform"

VERIFY_ONLY=false
MINIMAL=false
RESET_GRAFANA=false
BUILD_ALL=false
RETENTION_DAYS=365
LOG_MAX_SIZE="100m"
LOG_MAX_FILES=3

# Optional: load platform/.env so we can override defaults
if [[ -f "$PLATFORM_DIR/.env" ]]; then
  # shellcheck source=/dev/null
  set -a && source "$PLATFORM_DIR/.env" 2>/dev/null; set +a
  [[ -n "${OFDD_RETENTION_DAYS:-}" ]] && RETENTION_DAYS="${OFDD_RETENTION_DAYS}"
  [[ -n "${OFDD_LOG_MAX_SIZE:-}" ]] && LOG_MAX_SIZE="${OFDD_LOG_MAX_SIZE}"
  [[ -n "${OFDD_LOG_MAX_FILES:-}" ]] && LOG_MAX_FILES="${OFDD_LOG_MAX_FILES}"
fi

# Set after .env so a stray BUILD_SERVICES_STR in .env doesn't break --build
BUILD_SERVICES_STR=""

args=("$@")
i=0
while [[ $i -lt ${#args[@]} ]]; do
  arg="${args[$i]}"
  case "$arg" in
    --verify) VERIFY_ONLY=true ;;
    --minimal) MINIMAL=true ;;
    --reset-grafana) RESET_GRAFANA=true ;;
    --build-all) BUILD_ALL=true ;;
    --build)
      i=$(( i + 1 ))
      while [[ $i -lt ${#args[@]} ]] && [[ "${args[$i]}" != --* ]]; do
        BUILD_SERVICES_STR="${BUILD_SERVICES_STR} ${args[$i]}"
        i=$(( i + 1 ))
      done
      BUILD_SERVICES_STR="${BUILD_SERVICES_STR# }"   # trim leading space
      [[ -n "$BUILD_SERVICES_STR" ]] && i=$(( i - 1 ))   # back up so main loop doesn't skip next option
      ;;
    --retention-days) i=$(( i + 1 )); [[ $i -lt ${#args[@]} ]] && RETENTION_DAYS="${args[$i]}" ;;
    --log-max-size) i=$(( i + 1 )); [[ $i -lt ${#args[@]} ]] && LOG_MAX_SIZE="${args[$i]}" ;;
    --log-max-files) i=$(( i + 1 )); [[ $i -lt ${#args[@]} ]] && LOG_MAX_FILES="${args[$i]}" ;;
    -h|--help)
      echo "Usage: $0 [--verify|--minimal|--reset-grafana|--build SERVICE ...|--build-all] [--retention-days N] [--log-max-size SIZE] [--log-max-files N]"
      echo "  --verify            Show running services and DB status."
      echo "  --build SERVICE ... Rebuild and restart only these services (e.g. --build api). Then exit."
      echo "  --build-all         Rebuild and restart all containers. Then exit (no DB wait/migrations)."
      echo "  --retention-days N  TimescaleDB drop chunks older than N days (default 365)."
      echo "  --log-max-size SIZE Docker log max size per file (default 100m)."
      echo "  --log-max-files N   Docker log max number of files (default 3)."
      exit 0 ;;
  esac
  i=$(( i + 1 ))
done

check_prereqs() {
  command -v docker >/dev/null 2>&1 || { echo "Missing: docker"; exit 1; }
  command -v docker compose >/dev/null 2>&1 || command -v docker-compose >/dev/null 2>&1 || { echo "Missing: docker compose"; exit 1; }
}

verify() {
  echo "=== Services ==="
  docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null | head -15
  echo ""
  if docker exec openfdd_timescale pg_isready -U postgres -d openfdd 2>/dev/null; then
    echo "DB: localhost:5432/openfdd (OK)"
  else
    echo "DB: not reachable"
  fi
}

if $VERIFY_ONLY; then
  check_prereqs
  verify
  exit 0
fi

if $BUILD_ALL; then
  check_prereqs
  cd "$PLATFORM_DIR"
  echo "=== Rebuilding and restarting all containers ==="
  docker compose build && docker compose up -d
  echo "Done. All containers rebuilt and restarted."
  exit 0
fi

if $RESET_GRAFANA; then
  check_prereqs
  cd "$PLATFORM_DIR"
  echo "=== Resetting Grafana (wipe volume, re-apply provisioning) ==="
  docker compose stop grafana 2>/dev/null || true
  docker compose rm -f grafana 2>/dev/null || true
  vol=$(docker volume ls -q | grep grafana_data | head -1)
  [[ -n "$vol" ]] && docker volume rm "$vol" || true
  echo "Starting Grafana with fresh provisioning..."
  docker compose up -d grafana
  echo "Done. Open http://localhost:3000 (admin/admin)"
  exit 0
fi

# Rebuild and restart only specified services (e.g. after editing API static files)
if [[ -n "$BUILD_SERVICES_STR" ]]; then
  check_prereqs
  cd "$PLATFORM_DIR"
  echo "=== Rebuilding and restarting: $BUILD_SERVICES_STR ==="
  if docker compose build $BUILD_SERVICES_STR; then
    docker compose up -d $BUILD_SERVICES_STR
    echo "Done. Services restarted: $BUILD_SERVICES_STR"
  else
    echo "Build failed." >&2
    exit 1
  fi
  exit 0
fi

# Persist edge settings to platform/.env before starting stack (so compose picks up log opts)
write_edge_env() {
  local env_file="$PLATFORM_DIR/.env"
  [[ -f "$env_file" ]] || touch "$env_file"
  for key in OFDD_RETENTION_DAYS OFDD_LOG_MAX_SIZE OFDD_LOG_MAX_FILES; do
    case "$key" in
      OFDD_RETENTION_DAYS) val="$RETENTION_DAYS" ;;
      OFDD_LOG_MAX_SIZE) val="$LOG_MAX_SIZE" ;;
      OFDD_LOG_MAX_FILES) val="$LOG_MAX_FILES" ;;
    esac
    if grep -q "^${key}=" "$env_file" 2>/dev/null; then
      sed -i "s|^${key}=.*|${key}=${val}|" "$env_file"
    else
      echo "${key}=${val}" >> "$env_file"
    fi
  done
}
write_edge_env

check_prereqs
cd "$PLATFORM_DIR"

if $MINIMAL; then
  echo "=== Starting minimal stack (raw BACnet: DB + Grafana + BACnet server + scraper) ==="
  docker compose up -d --build db grafana bacnet-server bacnet-scraper
else
  echo "=== Building and starting full stack ==="
  docker compose up -d --build
fi

cd "$REPO_ROOT"

echo "=== Waiting for Postgres (~15s) ==="
for i in $(seq 1 30); do
  if docker exec openfdd_timescale pg_isready -U postgres -d openfdd 2>/dev/null; then
    echo "Postgres ready"
    break
  fi
  sleep 1
  [[ $i -eq 30 ]] && { echo "Postgres failed to start"; exit 1; }
done

echo "=== Applying migrations (idempotent; safe for existing DBs) ==="
(cd "$PLATFORM_DIR" && docker compose exec -T db psql -U postgres -d openfdd -f - < sql/004_fdd_input.sql) 2>/dev/null || true
(cd "$PLATFORM_DIR" && docker compose exec -T db psql -U postgres -d openfdd -f - < sql/005_bacnet_points.sql) 2>/dev/null || true
(cd "$PLATFORM_DIR" && docker compose exec -T db psql -U postgres -d openfdd -f - < sql/006_host_metrics.sql) 2>/dev/null || true
# Data retention: substitute RETENTION_DAYS (from --retention-days or .env)
(cd "$PLATFORM_DIR" && sed "s/365 days/${RETENTION_DAYS} days/g" sql/007_retention.sql | docker compose exec -T db psql -U postgres -d openfdd -f -) 2>/dev/null || true
(cd "$PLATFORM_DIR" && docker compose exec -T db psql -U postgres -d openfdd -f - < sql/008_fdd_run_log.sql) 2>/dev/null || true
(cd "$PLATFORM_DIR" && docker compose exec -T db psql -U postgres -d openfdd -f - < sql/009_analytics_motor_runtime.sql) 2>/dev/null || true

echo ""
echo "=== Bootstrap complete ==="
echo "  DB:       localhost:5432/openfdd  (postgres/postgres)"
echo "  Grafana:  http://localhost:3000   (admin/admin)"
if $MINIMAL; then
  echo "  BACnet:   http://localhost:8080   (diy-bacnet-server Swagger)"
  echo "  (Minimal: raw BACnet data only. No FDD, no weather, no API. Add full stack by re-running without --minimal.)"
else
  echo "  API:      http://localhost:8000   (docs: /docs)"
  echo "  BACnet:   http://localhost:8080   (diy-bacnet-server Swagger)"
fi
echo ""
echo "View logs: docker compose -f platform/docker-compose.yml logs -f"
echo ""
