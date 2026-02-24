#!/usr/bin/env bash
#
# open-fdd bootstrap: full Docker stack — DB, Grafana, BACnet server, BACnet scraper,
# weather scraper, FDD loop, host-stats, API, Caddy.
#
# Default behavior (no args):
#   ./scripts/bootstrap.sh
#     -> builds and starts the FULL stack
#
# Optional:
#   ./scripts/bootstrap.sh --install-docker     # attempt Docker install (Linux) then run
#   ./scripts/bootstrap.sh --minimal            # DB + Grafana + bacnet-server + bacnet-scraper only
#   ./scripts/bootstrap.sh --verify             # health checks only
#   ./scripts/bootstrap.sh --update             # git pull open-fdd + diy-bacnet-server sibling, rebuild, restart (keeps DB)
#   ./scripts/bootstrap.sh --maintenance        # safe prune only (NO volumes)
#   ./scripts/bootstrap.sh --build api ...      # rebuild and restart only selected services
#
# Site maintenance (pull both repos, prune, rebuild, verify):
#   ./scripts/bootstrap.sh --maintenance --update --verify
#
# Notes:
# - Requires docker + docker compose plugin (or docker-compose fallback)
# - If diy-bacnet-server sibling is missing, this script clones it.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
STACK_DIR="$REPO_ROOT/stack"

# -----------------------------
# Flags / defaults
# -----------------------------
VERIFY_ONLY=false
MINIMAL=false
RESET_GRAFANA=false
RESET_DATA=false
BUILD_ALL=false
UPDATE_PULL_REBUILD=false
MAINTENANCE_ONLY=false

INSTALL_DOCKER=false
SKIP_DOCKER_INSTALL=false

RETENTION_DAYS=365
LOG_MAX_SIZE="100m"
LOG_MAX_FILES=3

# Allow env overrides from stack/.env (if present)
if [[ -f "$STACK_DIR/.env" ]]; then
  # shellcheck source=/dev/null
  set -a && source "$STACK_DIR/.env" 2>/dev/null; set +a
  [[ -n "${OFDD_RETENTION_DAYS:-}" ]] && RETENTION_DAYS="${OFDD_RETENTION_DAYS}"
  [[ -n "${OFDD_LOG_MAX_SIZE:-}" ]] && LOG_MAX_SIZE="${OFDD_LOG_MAX_SIZE}"
  [[ -n "${OFDD_LOG_MAX_FILES:-}" ]] && LOG_MAX_FILES="${OFDD_LOG_MAX_FILES}"
fi

# Used by --build SERVICE ...
BUILD_SERVICES_STR=""

# Default repo to clone when diy-bacnet-server sibling is missing
DIY_BACNET_REPO_URL="${DIY_BACNET_REPO_URL:-https://github.com/bbartling/diy-bacnet-server.git}"

# -----------------------------
# Args
# -----------------------------
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
    --install-docker) INSTALL_DOCKER=true ;;
    --skip-docker-install) SKIP_DOCKER_INSTALL=true ;;
    --build)
      i=$(( i + 1 ))
      while [[ $i -lt ${#args[@]} ]] && [[ "${args[$i]}" != --* ]]; do
        BUILD_SERVICES_STR="${BUILD_SERVICES_STR} ${args[$i]}"
        i=$(( i + 1 ))
      done
      BUILD_SERVICES_STR="${BUILD_SERVICES_STR# }" # trim leading space
      [[ -n "$BUILD_SERVICES_STR" ]] && i=$(( i - 1 )) # back up one
      ;;
    --retention-days) i=$(( i + 1 )); [[ $i -lt ${#args[@]} ]] && RETENTION_DAYS="${args[$i]}" ;;
    --log-max-size)   i=$(( i + 1 )); [[ $i -lt ${#args[@]} ]] && LOG_MAX_SIZE="${args[$i]}" ;;
    --log-max-files)  i=$(( i + 1 )); [[ $i -lt ${#args[@]} ]] && LOG_MAX_FILES="${args[$i]}" ;;
    -h|--help)
      cat <<EOF
Usage: $0 [options]

Core:
  (no args)                 Build + start full stack (ALL services)
  --minimal                 Start minimal stack (db, grafana, bacnet-server, bacnet-scraper)
  --verify                  Show running services + health checks
  --update                  Git pull open-fdd + diy-bacnet-server (sibling), rebuild, restart (keeps DB)
  --maintenance             Safe Docker prune only (NO volumes)

  Site maintenance:  $0 --maintenance --update --verify

Build controls:
  --build SERVICE ...       Rebuild + restart only these services, then exit
  --build-all               Rebuild + restart all services, then exit

Data / ops:
  --reset-grafana           Wipe Grafana volume and restart Grafana
  --reset-data              Delete all sites via API + POST /data-model/reset (testing)

Edge settings:
  --retention-days N        TimescaleDB retention window (default 365)
  --log-max-size SIZE       Docker log max size per file (default 100m)
  --log-max-files N         Docker log max number of rotated files (default 3)

Docker install:
  --install-docker          Attempt to install Docker (Linux only) then continue
  --skip-docker-install     Explicitly skip Docker install (no-op)

EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $arg"
      echo "Run: $0 --help"
      exit 1
      ;;
  esac
  i=$(( i + 1 ))
done

# -----------------------------
# Helpers
# -----------------------------
have_cmd() { command -v "$1" >/dev/null 2>&1; }

need_root_or_sudo() {
  if [[ "${EUID:-$(id -u)}" -ne 0 ]] && ! have_cmd sudo; then
    echo "Need root or sudo for this action."
    exit 1
  fi
}

as_root() {
  if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

detect_linux_id() {
  # echoes ID and ID_LIKE (best effort)
  if [[ -r /etc/os-release ]]; then
    # shellcheck disable=SC1091
    source /etc/os-release
    echo "${ID:-unknown}|${ID_LIKE:-}"
  else
    echo "unknown|"
  fi
}

install_docker_linux() {
  # Conservative installer (focus on Ubuntu/Debian + Raspberry Pi OS + derivatives).
  # If distro is unknown, we print instructions and exit non-fatally.
  if [[ "$(uname -s)" != "Linux" ]]; then
    echo "Docker install: unsupported OS ($(uname -s)). Install Docker manually, then re-run."
    return 1
  fi

  local os_id os_like
  IFS="|" read -r os_id os_like <<<"$(detect_linux_id)"

  echo "=== Docker install requested (OS: ${os_id}, like: ${os_like}) ==="

  # If docker already exists, do nothing.
  if have_cmd docker; then
    echo "Docker already installed: $(docker --version 2>/dev/null || true)"
    return 0
  fi

  # Debian/Ubuntu/Raspbian
  if [[ "$os_id" =~ ^(ubuntu|debian|raspbian)$ ]] || [[ "$os_like" == *debian* ]]; then
    need_root_or_sudo
    echo "Installing Docker using apt (debian/ubuntu style)..."

    as_root apt-get update -y
    as_root apt-get install -y ca-certificates curl gnupg lsb-release

    # Prefer the convenience script for simplicity in edge installs.
    # If you want repo-key install instead, swap this section later.
    curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
    as_root sh /tmp/get-docker.sh
    rm -f /tmp/get-docker.sh

    # Enable and start docker
    as_root systemctl enable --now docker || true

    # Add current user to docker group (requires relogin to take effect)
    if have_cmd groupadd && have_cmd usermod; then
      as_root groupadd -f docker || true
      as_root usermod -aG docker "${SUDO_USER:-$USER}" || true
      echo "NOTE: You may need to log out/in (or reboot) for docker group permission to apply."
    fi

    return 0
  fi

  echo "Docker install: unsupported/unknown distro for auto-install."
  echo "Install Docker manually, then re-run this script."
  return 1
}

docker_compose_cmd() {
  # Prefer modern plugin: `docker compose`
  if docker compose version >/dev/null 2>&1; then
    echo "docker compose"
    return 0
  fi
  # Fallback
  if have_cmd docker-compose; then
    echo "docker-compose"
    return 0
  fi
  return 1
}

check_prereqs() {
  if ! have_cmd docker; then
    echo "Missing: docker"
    echo "  - Re-run with: $0 --install-docker"
    echo "  - Or install Docker manually."
    exit 1
  fi
  if ! docker_compose_cmd >/dev/null 2>&1; then
    echo "Missing: docker compose"
    echo "  - Install docker compose plugin, or docker-compose."
    exit 1
  fi
}

write_edge_env() {
  local env_file="$STACK_DIR/.env"
  [[ -f "$env_file" ]] || touch "$env_file"

  # Use sed -i portability: GNU sed vs BSD sed
  local sed_i=(-i)
  if sed --version >/dev/null 2>&1; then
    sed_i=(-i)
  else
    sed_i=(-i "")
  fi

  for key in OFDD_RETENTION_DAYS OFDD_LOG_MAX_SIZE OFDD_LOG_MAX_FILES; do
    local val=""
    case "$key" in
      OFDD_RETENTION_DAYS) val="$RETENTION_DAYS" ;;
      OFDD_LOG_MAX_SIZE)   val="$LOG_MAX_SIZE" ;;
      OFDD_LOG_MAX_FILES)  val="$LOG_MAX_FILES" ;;
    esac

    if grep -q "^${key}=" "$env_file" 2>/dev/null; then
      sed "${sed_i[@]}" "s|^${key}=.*|${key}=${val}|" "$env_file"
    else
      echo "${key}=${val}" >> "$env_file"
    fi
  done
}

ensure_diy_bacnet_sibling() {
  local parent_dir sibling
  parent_dir="$(cd "$REPO_ROOT/.." && pwd)"
  sibling="$parent_dir/diy-bacnet-server"

  if [[ -d "$sibling" ]]; then
    return 0
  fi

  if ! have_cmd git; then
    echo "Missing: git (required to clone diy-bacnet-server sibling)."
    echo "Clone it manually:"
    echo "  git clone $DIY_BACNET_REPO_URL $sibling"
    exit 1
  fi

  echo "=== Cloning diy-bacnet-server (sibling of open-fdd) ==="
  (cd "$parent_dir" && git clone "$DIY_BACNET_REPO_URL" diy-bacnet-server) || {
    echo "Clone failed. Clone manually:"
    echo "  git clone $DIY_BACNET_REPO_URL $sibling"
    exit 1
  }
  echo "Cloned: $sibling"
}

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
    echo "  → Start stack: ./scripts/bootstrap.sh  (or: cd STACK && $(docker_compose_cmd) up -d db grafana)"
  fi

  if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx openfdd_grafana; then
    echo "Grafana: running — http://localhost:3000"
  else
    echo "Grafana: not running — start stack: ./scripts/bootstrap.sh"
  fi

  echo ""
  echo "=== Feature checks (BACnet + API, up to 5 tries / 10s apart) ==="
  if curl_retry 5 10 -X POST http://localhost:8080/server_hello -H "Content-Type: application/json" \
      -d '{"jsonrpc":"2.0","id":"0","method":"server_hello","params":{}}'; then
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

wait_for_api() {
  API_BASE="${OFDD_API_URL:-http://localhost:8000}"
  API_BASE="${API_BASE%/}"

  echo "=== Waiting for API at $API_BASE (~60s) ==="
  local try=1
  while [[ $try -le 30 ]]; do
    if curl -sf --connect-timeout 3 "$API_BASE/health" >/dev/null 2>&1; then
      echo "API ready."
      return 0
    fi
    sleep 2
    try=$(( try + 1 ))
  done

  echo "API not reachable at $API_BASE."
  return 1
}

seed_config_via_api() {
  if ! wait_for_api; then
    echo "Skipping config seed (API not reachable)."
    return 1
  fi

  echo "=== Seeding STACK config (PUT /config) ==="
  local body
  body=$(python3 -c "
import json, os
def env(key, default):
    v = os.environ.get(key, default)
    if v in ('true','True','TRUE'): return True
    if v in ('false','False','FALSE'): return False
    try: return int(v)
    except ValueError: pass
    try: return float(v)
    except ValueError: pass
    return v
print(json.dumps({
    'rule_interval_hours': env('OFDD_RULE_INTERVAL_HOURS', 0.1),
    'lookback_days': env('OFDD_LOOKBACK_DAYS', 3),
    'rules_dir': os.environ.get('OFDD_RULES_DIR', 'analyst/rules'),
    'brick_ttl_dir': os.environ.get('OFDD_BRICK_TTL_DIR', 'config'),
    'bacnet_enabled': env('OFDD_BACNET_SCRAPE_ENABLED', True),
    'bacnet_scrape_interval_min': env('OFDD_BACNET_SCRAPE_INTERVAL_MIN', 1),
    'bacnet_server_url': os.environ.get('OFDD_BACNET_SERVER_URL', 'http://localhost:8080'),
    'bacnet_site_id': os.environ.get('OFDD_BACNET_SITE_ID', 'default'),
    'open_meteo_enabled': env('OFDD_OPEN_METEO_ENABLED', True),
    'open_meteo_interval_hours': env('OFDD_OPEN_METEO_INTERVAL_HOURS', 24),
    'open_meteo_latitude': env('OFDD_OPEN_METEO_LATITUDE', 41.88),
    'open_meteo_longitude': env('OFDD_OPEN_METEO_LONGITUDE', -87.63),
    'open_meteo_timezone': os.environ.get('OFDD_OPEN_METEO_TIMEZONE', 'America/Chicago'),
    'open_meteo_days_back': env('OFDD_OPEN_METEO_DAYS_BACK', 3),
    'open_meteo_site_id': os.environ.get('OFDD_OPEN_METEO_SITE_ID', 'default'),
    'graph_sync_interval_min': env('OFDD_GRAPH_SYNC_INTERVAL_MIN', 5),
}))
" 2>/dev/null) || body="{\"rule_interval_hours\":0.1,\"lookback_days\":3,\"rules_dir\":\"analyst/rules\",\"brick_ttl_dir\":\"config\",\"bacnet_enabled\":true,\"bacnet_scrape_interval_min\":1,\"bacnet_server_url\":\"http://localhost:8080\",\"bacnet_site_id\":\"default\",\"open_meteo_enabled\":true,\"open_meteo_interval_hours\":24,\"open_meteo_latitude\":41.88,\"open_meteo_longitude\":-87.63,\"open_meteo_timezone\":\"America/Chicago\",\"open_meteo_days_back\":3,\"open_meteo_site_id\":\"default\",\"graph_sync_interval_min\":5}"

  if curl -sf -X PUT "$API_BASE/config" -H "Content-Type: application/json" -d "$body" >/dev/null 2>&1; then
    echo "  PUT /config OK (config stored in RDF)."
  else
    echo "  PUT /config failed (non-fatal; set config via API or /app/ later)."
    return 1
  fi
  return 0
}

reset_data_via_api() {
  if ! wait_for_api; then
    echo "Skip --reset-data (API not reachable)."
    return 1
  fi

  local sites_json ids
  sites_json="$(curl -sf -H "Accept: application/json" "$API_BASE/sites" 2>/dev/null)" || {
    echo "GET /sites failed."
    return 1
  }

  ids="$(echo "$sites_json" | grep -o '"id":"[^"]*"' | sed 's/"id":"//;s/"$//')"

  if [[ -n "$ids" ]]; then
    while IFS= read -r id; do
      [[ -z "$id" ]] && continue
      if curl -sf -X DELETE "$API_BASE/sites/$id" >/dev/null 2>&1; then
        echo "  Deleted site $id"
      else
        echo "  Failed to delete site $id"
      fi
    done <<< "$ids"
  else
    echo "  No sites to delete."
  fi

  if curl -sf -X POST "$API_BASE/data-model/reset" -H "Content-Type: application/json" -d '{}' >/dev/null 2>&1; then
    echo "  POST /data-model/reset OK."
  else
    echo "  POST /data-model/reset failed."
    return 1
  fi

  echo "Data model is now empty (no sites, no Brick triples, no BACnet)."
  return 0
}

wait_for_postgres_or_die() {
  echo "=== Waiting for Postgres (~15s) ==="
  for _ in $(seq 1 30); do
    if docker exec openfdd_timescale pg_isready -U postgres -d openfdd 2>/dev/null; then
      echo "Postgres ready"
      return 0
    fi
    sleep 1
  done
  echo "Postgres failed to start"
  exit 1
}

apply_migrations_best_effort() {
  echo "=== Applying migrations (idempotent; safe for existing DBs) ==="
  local dc
  dc="$(docker_compose_cmd)"
  (
    cd "$STACK_DIR"
    $dc exec -T db psql -U postgres -d openfdd -f - < sql/004_fdd_input.sql 2>/dev/null || true
    $dc exec -T db psql -U postgres -d openfdd -f - < sql/005_bacnet_points.sql 2>/dev/null || true
    $dc exec -T db psql -U postgres -d openfdd -f - < sql/006_host_metrics.sql 2>/dev/null || true
    sed "s/365 days/${RETENTION_DAYS} days/g" sql/007_retention.sql | $dc exec -T db psql -U postgres -d openfdd -f - 2>/dev/null || true
    $dc exec -T db psql -U postgres -d openfdd -f - < sql/008_fdd_run_log.sql 2>/dev/null || true
    $dc exec -T db psql -U postgres -d openfdd -f - < sql/009_analytics_motor_runtime.sql 2>/dev/null || true
    $dc exec -T db psql -U postgres -d openfdd -f - < sql/010_equipment_feeds.sql 2>/dev/null || true
    $dc exec -T db psql -U postgres -d openfdd -f - < sql/011_polling.sql 2>/dev/null || true
  )
}

safe_docker_prune() {
  echo "=== Docker maintenance (safe: no volume prune) ==="
  echo "Removing stopped containers..."
  docker container prune -f
  echo "Removing dangling images..."
  docker image prune -f
  echo "Removing build cache..."
  docker builder prune -f 2>/dev/null || true
  echo "Done. Volumes were NOT pruned (TimescaleDB and Grafana data retained)."
}

# -----------------------------
# Optional Docker install
# -----------------------------
if $INSTALL_DOCKER && ! $SKIP_DOCKER_INSTALL; then
  install_docker_linux || true
fi

# -----------------------------
# Early exit modes
# -----------------------------
if $VERIFY_ONLY && ! $UPDATE_PULL_REBUILD; then
  check_prereqs
  verify
  exit 0
fi

if $MAINTENANCE_ONLY && ! $UPDATE_PULL_REBUILD; then
  check_prereqs
  safe_docker_prune
  exit 0
fi

# From here on, we run stack operations (default/no args = FULL stack)
write_edge_env
check_prereqs
ensure_diy_bacnet_sibling

dc="$(docker_compose_cmd)"

# -----------------------------
# --update flow
# -----------------------------
if $UPDATE_PULL_REBUILD; then
  echo "=== Update: git pull + rebuild (TimescaleDB retained) ==="
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
  if [[ -n "$PRE_OPENFDD" && -n "$POST_OPENFDD" && "$PRE_OPENFDD" == "$POST_OPENFDD" ]] && \
     [[ -n "$PRE_BACNET" && -n "$POST_BACNET" && "$PRE_BACNET" == "$POST_BACNET" ]]; then
    SKIP_BUILD=true
  fi

  if $MAINTENANCE_ONLY; then
    safe_docker_prune
  fi

  cd "$STACK_DIR"
  if $SKIP_BUILD; then
    echo "No new commits detected; restarting containers only."
    $dc up -d
  else
    echo "Rebuilding all images and restarting stack..."
    $dc build
    $dc up -d
  fi
  cd "$REPO_ROOT"

  if ! $SKIP_BUILD; then
    wait_for_postgres_or_die
    apply_migrations_best_effort
  else
    echo "Skipping Postgres wait/migrations (no new commits; assuming schema unchanged)."
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

# -----------------------------
# --build-all
# -----------------------------
if $BUILD_ALL; then
  cd "$STACK_DIR"
  echo "=== Rebuilding and restarting all containers ==="
  $dc build
  $dc up -d
  echo "Done. All containers rebuilt and restarted."
  exit 0
fi

# -----------------------------
# --reset-grafana
# -----------------------------
if $RESET_GRAFANA; then
  cd "$STACK_DIR"
  echo "=== Resetting Grafana (wipe volume, re-apply provisioning) ==="
  $dc stop grafana 2>/dev/null || true
  $dc rm -f grafana 2>/dev/null || true
  vol="$(docker volume ls -q | grep grafana_data | head -1 || true)"
  [[ -n "${vol:-}" ]] && docker volume rm "$vol" || true
  echo "Starting Grafana with fresh provisioning..."
  $dc up -d grafana
  echo "Done. Open http://localhost:3000 (admin/admin)"
  exit 0
fi

# -----------------------------
# --build SERVICE ...
# -----------------------------
if [[ -n "$BUILD_SERVICES_STR" ]]; then
  cd "$STACK_DIR"
  echo "=== Rebuilding and restarting: $BUILD_SERVICES_STR ==="
  $dc build $BUILD_SERVICES_STR
  $dc up -d $BUILD_SERVICES_STR
  echo "Done. Services restarted: $BUILD_SERVICES_STR"
  exit 0
fi

# -----------------------------
# Default run (NO ARGS): FULL STACK
# -----------------------------
cd "$STACK_DIR"

if $MINIMAL; then
  echo "=== Starting minimal stack (raw BACnet: DB + Grafana + BACnet server + scraper) ==="
  $dc up -d --build db grafana bacnet-server bacnet-scraper
else
  echo "=== Building and starting full stack ==="
  $dc up -d --build
fi

cd "$REPO_ROOT"

wait_for_postgres_or_die
apply_migrations_best_effort

if ! $MINIMAL; then
  echo ""
  seed_config_via_api || true
fi

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
  echo "  (Minimal: raw BACnet data only. No FDD, no weather, no API.)"
else
  echo "  API:      http://localhost:8000   (docs: /docs)"
  echo "  BACnet:   http://localhost:8080   (diy-bacnet-server Swagger)"
fi
echo ""
echo "Verify all services: ./scripts/bootstrap.sh --verify"
echo "View logs: $(docker_compose_cmd) -f stack/docker-compose.yml logs -f"
echo ""