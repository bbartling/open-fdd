#!/bin/bash
#
# open-fdd bootstrap: full Docker stack — DB, Grafana, BACnet server, BACnet scraper, weather scraper, FDD loop, host-stats, API, Caddy.
#
# Build and start everything (from repo root):
#   ./scripts/bootstrap.sh
# (Runs: cd platform && docker compose up -d --build — builds all images and starts all services.)
#
# Logs:
#   docker logs -f openfdd_fdd_loop 
#   docker logs -f openfdd_api
#   docker logs -f openfdd_bacnet_scraper
#   docker logs -f openfdd_weather_scraper
#   docker logs -f openfdd_weather_scraper 

# Usage:
#   ./scripts/bootstrap.sh            # Build and start full stack (all services)
#   ./scripts/bootstrap.sh --verify   # Check what's running
#   ./scripts/bootstrap.sh --minimal  # Raw BACnet only: DB + Grafana + bacnet-server + bacnet-scraper (no FDD, weather, API)
#   ./scripts/bootstrap.sh --build bacnet-server   # Rebuild diy-bacnet-server (e.g. after pulling sibling repo)
#   ./scripts/bootstrap.sh --build api   # Rebuild and restart only the API
#   ./scripts/bootstrap.sh --build api bacnet-scraper fdd-loop weather-scraper   # Rebuild API + scrapers + FDD loop
#   ./scripts/bootstrap.sh --build-all  # Rebuild all images and start all containers (deploys everything; no DB wait/migrations)
#   ./scripts/bootstrap.sh --update     # Git pull open-fdd + diy-bacnet-server, rebuild all, restart (keeps DB)
#   ./scripts/bootstrap.sh --update --maintenance  # Same as --update, plus safe prune before rebuild; volumes kept
#   ./scripts/bootstrap.sh --update --maintenance --verify  # Update + prune + rebuild, then curl :8080 and :8000
# If diy-bacnet-server is not present as a sibling, bootstrap clones it (override: DIY_BACNET_REPO_URL).
#   ./scripts/bootstrap.sh --maintenance  # Safe Docker prune only (containers, images, build cache; no volumes)
#   ./scripts/bootstrap.sh --reset-grafana  # Wipe Grafana volume (fix provisioning); restarts Grafana
#   ./scripts/bootstrap.sh --reset-data     # After stack is up: delete all sites via API + POST /data-model/reset (testing). Use OFDD_API_URL if API is not at :8000.
#   ./scripts/bootstrap.sh --retention-days 180   # TimescaleDB retention (default 365)
#   ./scripts/bootstrap.sh --log-max-size 50m --log-max-files 2   # Docker log rotation (default 100m, 3)
#
# Prerequisite: diy-bacnet-server as sibling of open-fdd (for BACnet stack).
# If the sibling is missing, bootstrap clones it (see ensure_diy_bacnet_sibling below).
#

set -e
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PLATFORM_DIR="$REPO_ROOT/platform"

VERIFY_ONLY=false
MINIMAL=false
RESET_GRAFANA=false
RESET_DATA=false
BUILD_ALL=false
UPDATE_PULL_REBUILD=false
MAINTENANCE_ONLY=false
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
    --reset-data) RESET_DATA=true ;;
    --build-all) BUILD_ALL=true ;;
    --update) UPDATE_PULL_REBUILD=true ;;
    --maintenance) MAINTENANCE_ONLY=true ;;
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
      echo "Usage: $0 [--verify|--minimal|--update|--maintenance|--reset-grafana|--reset-data|--build SERVICE ...|--build-all] [--retention-days N] [--log-max-size SIZE] [--log-max-files N]"
      echo "  --verify            Show running services and DB status."
      echo "  --reset-data        After stack up: delete all sites via API + POST /data-model/reset (empty data model for testing). Uses API at OFDD_API_URL or http://localhost:8000."
      echo "  --update            Git pull open-fdd + diy-bacnet-server (sibling), rebuild all images, restart stack. Keeps TimescaleDB data."
      echo "  --update --maintenance  Same as --update, then run safe prune before rebuild (containers, images, build cache; volumes kept)."
      echo "  --update --maintenance --verify  Update, prune, rebuild, then run health checks (curl BACnet :8080, API :8000, DB)."
      echo "  --verify            Run health checks only (curl localhost:8080 diy-bacnet-server, localhost:8000 API, DB). Use with --update to verify after update."
      echo "  --maintenance       Safe Docker prune only: stopped containers, dangling images, build cache. Does NOT prune volumes (DB data safe)."
      echo "  --build SERVICE ... Rebuild and restart only these services (e.g. --build api). Then exit."
      echo "  --build-all         Rebuild and restart all containers. Then exit (no DB wait/migrations)."
      echo "  --retention-days N  TimescaleDB drop chunks older than N days (default 365)."
      echo "  --log-max-size SIZE Docker log max size per file (default 100m)."
      echo "  --log-max-files N   Docker log max number of files (default 3)."
      exit 0 ;;
  esac
  i=$(( i + 1 ))
done

# Default repo to clone when diy-bacnet-server sibling is missing (override with DIY_BACNET_REPO_URL)
DIY_BACNET_REPO_URL="${DIY_BACNET_REPO_URL:-https://github.com/bbartling/diy-bacnet-server.git}"

check_prereqs() {
  command -v docker >/dev/null 2>&1 || { echo "Missing: docker"; exit 1; }
  command -v docker compose >/dev/null 2>&1 || command -v docker-compose >/dev/null 2>&1 || { echo "Missing: docker compose"; exit 1; }
}

# Clone diy-bacnet-server as sibling of open-fdd if missing (so docker compose build bacnet-server works)
ensure_diy_bacnet_sibling() {
  local parent_dir
  parent_dir="$(cd "$REPO_ROOT/.." && pwd)"
  local sibling="$parent_dir/diy-bacnet-server"
  if [[ -d "$sibling" ]]; then
    return 0
  fi
  command -v git >/dev/null 2>&1 || { echo "Missing: git (required to clone diy-bacnet-server). Clone it manually: git clone $DIY_BACNET_REPO_URL $sibling"; exit 1; }
  echo "=== Cloning diy-bacnet-server (sibling of open-fdd) ==="
  (cd "$parent_dir" && git clone "$DIY_BACNET_REPO_URL" diy-bacnet-server) || { echo "Clone failed. Clone manually: git clone $DIY_BACNET_REPO_URL $sibling"; exit 1; }
  echo "Cloned: $sibling"
}

# Persist edge settings to platform/.env (so compose picks up log opts). Must be defined before --update uses it.
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

# Try a command up to max_tries times, sleeping sleep_sec between attempts. Return 0 on first success.
curl_retry() {
  local max_tries="${1:-5}"
  local sleep_sec="${2:-10}"
  shift 2
  local try=1
  while [[ $try -le $max_tries ]]; do
    if curl -sf --connect-timeout 3 "$@" >/dev/null 2>&1; then
      return 0
    fi
    [[ $try -lt $max_tries ]] && sleep "$sleep_sec"
    try=$(( try + 1 ))
  done
  return 1
}

verify() {
  echo "=== Services ==="
  docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null | head -15
  echo ""
  if docker exec openfdd_timescale pg_isready -U postgres -d openfdd 2>/dev/null; then
    echo "DB: localhost:5432/openfdd (OK)"
  else
    echo "DB: not reachable"
    echo "  → Start stack: ./scripts/bootstrap.sh  (or: cd platform && docker compose up -d db grafana)"
  fi
  if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx openfdd_grafana; then
    echo "Grafana: running — http://localhost:3000 (or http://<this-host-ip>:3000 from another machine)"
  else
    echo "Grafana: not running — start stack: ./scripts/bootstrap.sh  (listens on 0.0.0.0:3000 when up)"
  fi
  echo ""
  echo "=== Feature checks (BACnet + API, up to 5 tries / 10s apart) ==="
  if curl_retry 5 10 -X POST http://localhost:8080/server_hello -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","id":"0","method":"server_hello","params":{}}'; then
    echo "BACnet: http://localhost:8080 (OK — server_hello responded)"
  else
    echo "BACnet: http://localhost:8080 (not reachable or no response after 5 tries)"
  fi
  if curl_retry 5 10 http://localhost:8000/health; then
    echo "API:    http://localhost:8000 (OK — /health responded)"
  else
    echo "API:    http://localhost:8000 (not reachable after 5 tries; run full stack without --minimal)"
  fi
  echo ""
}

# Delete all sites via API and POST /data-model/reset (same as tools/delete_all_sites_and_reset.py). Uses OFDD_API_URL or http://localhost:8000.
reset_data_via_api() {
  local api_base="${OFDD_API_URL:-http://localhost:8000}"
  api_base="${api_base%/}"
  echo "=== Waiting for API at $api_base (~60s) ==="
  local try=1
  while [[ $try -le 30 ]]; do
    if curl -sf --connect-timeout 3 "$api_base/health" >/dev/null 2>&1; then
      echo "API ready."
      break
    fi
    sleep 2
    try=$(( try + 1 ))
    [[ $try -gt 30 ]] && { echo "API not reachable at $api_base; skip --reset-data."; return 1; }
  done
  echo "=== Resetting data model (DELETE all sites, POST /data-model/reset) ==="
  local sites_json
  sites_json="$(curl -sf -H "Accept: application/json" "$api_base/sites" 2>/dev/null)" || { echo "GET /sites failed."; return 1; }
  local ids
  ids="$(echo "$sites_json" | grep -o '"id":"[^"]*"' | sed 's/"id":"//;s/"$//')"
  if [[ -n "$ids" ]]; then
    local id
    while IFS= read -r id; do
      [[ -z "$id" ]] && continue
      if curl -sf -X DELETE "$api_base/sites/$id" >/dev/null 2>&1; then
        echo "  Deleted site $id"
      else
        echo "  Failed to delete site $id"
      fi
    done <<< "$ids"
  else
    echo "  No sites to delete."
  fi
  if curl -sf -X POST "$api_base/data-model/reset" -H "Content-Type: application/json" -d '{}' >/dev/null 2>&1; then
    echo "  POST /data-model/reset OK."
  else
    echo "  POST /data-model/reset failed."
    return 1
  fi
  echo "Data model is now empty (no sites, no Brick triples, no BACnet)."
  return 0
}

# Verify-only mode: run health checks and exit (unless we're also doing --update, then verify runs at end of update)
if $VERIFY_ONLY && ! $UPDATE_PULL_REBUILD; then
  check_prereqs
  verify
  exit 0
fi

# Safe Docker maintenance: remove stopped containers, dangling images, build cache. Never prunes volumes (TimescaleDB data preserved).
if $MAINTENANCE_ONLY && ! $UPDATE_PULL_REBUILD; then
  check_prereqs
  echo "=== Docker maintenance (safe: no volume prune) ==="
  echo "Removing stopped containers..."
  docker container prune -f
  echo "Removing dangling images..."
  docker image prune -f
  echo "Removing build cache..."
  docker builder prune -f 2>/dev/null || true
  echo "Done. Volumes were NOT pruned (TimescaleDB and Grafana data retained)."
  exit 0
fi

if $UPDATE_PULL_REBUILD; then
  check_prereqs
  ensure_diy_bacnet_sibling
  write_edge_env
  echo "=== Update: git pull + rebuild (data in TimescaleDB retained) ==="
  DIY_BACNET="$REPO_ROOT/../diy-bacnet-server"
  PRE_OPENFDD=""
  PRE_BACNET=""
  [[ -d "$REPO_ROOT/.git" ]] && PRE_OPENFDD=$(cd "$REPO_ROOT" && git rev-parse HEAD 2>/dev/null) || true
  [[ -d "$DIY_BACNET/.git" ]] && PRE_BACNET=$(cd "$DIY_BACNET" && git rev-parse HEAD 2>/dev/null) || true

  if [[ -d "$REPO_ROOT/.git" ]]; then
    echo "Pulling open-fdd..."
    (cd "$REPO_ROOT" && git pull --rebase 2>/dev/null || git pull 2>/dev/null) || true
  else
    echo "Skipping open-fdd git pull (not a git repo)."
  fi
  if [[ -d "$DIY_BACNET/.git" ]]; then
    echo "Pulling diy-bacnet-server (sibling)..."
    (cd "$DIY_BACNET" && git pull --rebase 2>/dev/null || git pull 2>/dev/null) || true
  else
    echo "Skipping diy-bacnet-server git pull (sibling not found or not a git repo)."
  fi

  POST_OPENFDD=""
  POST_BACNET=""
  [[ -d "$REPO_ROOT/.git" ]] && POST_OPENFDD=$(cd "$REPO_ROOT" && git rev-parse HEAD 2>/dev/null) || true
  [[ -d "$DIY_BACNET/.git" ]] && POST_BACNET=$(cd "$DIY_BACNET" && git rev-parse HEAD 2>/dev/null) || true
  SKIP_BUILD=false
  if [[ -n "$PRE_OPENFDD" && -n "$POST_OPENFDD" && "$PRE_OPENFDD" = "$POST_OPENFDD" ]] && \
     [[ -n "$PRE_BACNET" && -n "$POST_BACNET" && "$PRE_BACNET" = "$POST_BACNET" ]]; then
    SKIP_BUILD=true
  fi

  if $MAINTENANCE_ONLY; then
    echo "Running Docker maintenance (prune) before rebuild..."
    docker container prune -f
    docker image prune -f
    docker builder prune -f 2>/dev/null || true
  fi
  cd "$PLATFORM_DIR"
  if $SKIP_BUILD; then
    echo "No new commits in open-fdd or diy-bacnet-server; skipping image rebuild, restarting containers only."
    docker compose up -d
  else
    echo "Rebuilding all images and restarting stack..."
    docker compose build && docker compose up -d
  fi
  cd "$REPO_ROOT"
  if ! $SKIP_BUILD; then
    echo "=== Waiting for Postgres (~15s) ==="
    for i in $(seq 1 30); do
      if docker exec openfdd_timescale pg_isready -U postgres -d openfdd 2>/dev/null; then
        echo "Postgres ready"
        break
      fi
      sleep 1
      [[ $i -eq 30 ]] && { echo "Postgres failed to start"; exit 1; }
    done
    echo "=== Applying migrations (idempotent) ==="
    (cd "$PLATFORM_DIR" && docker compose exec -T db psql -U postgres -d openfdd -f - < sql/004_fdd_input.sql) 2>/dev/null || true
    (cd "$PLATFORM_DIR" && docker compose exec -T db psql -U postgres -d openfdd -f - < sql/005_bacnet_points.sql) 2>/dev/null || true
    (cd "$PLATFORM_DIR" && docker compose exec -T db psql -U postgres -d openfdd -f - < sql/006_host_metrics.sql) 2>/dev/null || true
    (cd "$PLATFORM_DIR" && sed "s/365 days/${RETENTION_DAYS} days/g" sql/007_retention.sql | docker compose exec -T db psql -U postgres -d openfdd -f -) 2>/dev/null || true
    (cd "$PLATFORM_DIR" && docker compose exec -T db psql -U postgres -d openfdd -f - < sql/008_fdd_run_log.sql) 2>/dev/null || true
    (cd "$PLATFORM_DIR" && docker compose exec -T db psql -U postgres -d openfdd -f - < sql/009_analytics_motor_runtime.sql) 2>/dev/null || true
    (cd "$PLATFORM_DIR" && docker compose exec -T db psql -U postgres -d openfdd -f - < sql/010_equipment_feeds.sql) 2>/dev/null || true
    (cd "$PLATFORM_DIR" && docker compose exec -T db psql -U postgres -d openfdd -f - < sql/011_polling.sql) 2>/dev/null || true
  else
    echo "Skipping Postgres wait and migrations (no new commits; schema unchanged)."
  fi
  echo ""
  echo "=== Update complete ==="
  echo "  DB data retained. API: http://localhost:8000  BACnet: http://localhost:8080"
  if $VERIFY_ONLY; then
    echo ""
    verify
  else
    echo "  Verify: ./scripts/bootstrap.sh --verify"
  fi
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

write_edge_env

check_prereqs
ensure_diy_bacnet_sibling
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
(cd "$PLATFORM_DIR" && docker compose exec -T db psql -U postgres -d openfdd -f - < sql/010_equipment_feeds.sql) 2>/dev/null || true
(cd "$PLATFORM_DIR" && docker compose exec -T db psql -U postgres -d openfdd -f - < sql/011_polling.sql) 2>/dev/null || true

if $RESET_DATA; then
  echo ""
  reset_data_via_api || true
fi

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
echo "Verify all services: ./scripts/bootstrap.sh --verify"
echo "Test CRUD + SPARQL:  python tools/test_crud_api.py  (optional: BACNET_URL=http://localhost:8080)"
echo "Test graph + CRUD:  python tools/graph_and_crud_test.py  (in-memory graph, serialize, SPARQL; optional: BACNET_URL=...)"
echo "View logs: docker compose -f platform/docker-compose.yml logs -f"
echo ""
