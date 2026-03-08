#!/usr/bin/env bash
#
# open-fdd bootstrap: full Docker stack — DB, Grafana, BACnet server, BACnet scraper,
# weather scraper, FDD loop, host-stats, API, Caddy.
#
# Default behavior (no args):
#   ./scripts/bootstrap.sh
#     -> builds and starts the FULL stack (Grafana is NOT started by default)
#
# Optional: --with-grafana   Include Grafana (and /grafana route via Caddy) in the stack.
# Optional: --with-mqtt-bridge   Enable BACnet2MQTT bridge + MQTT broker (localhost:1883) for Home Assistant on same box.
#   BACnet gateway: http://localhost:8080/docs (Swagger). POST server_hello returns mqtt_bridge status when bridge enabled.
#
# Optional (single-purpose):
#   ./scripts/bootstrap.sh --install-docker     # attempt Docker install (Linux) then run
#   ./scripts/bootstrap.sh --minimal            # DB + bacnet-server + bacnet-scraper only (add --with-grafana for Grafana)
#   ./scripts/bootstrap.sh --verify             # health checks only
#   ./scripts/bootstrap.sh --test             # run tests: frontend (lint + typecheck + vitest), backend (pytest), Caddy validate; then exit. Does not run E2E/Selenium or long-running tests.
#   ./scripts/bootstrap.sh --update             # git pull open-fdd + diy-bacnet-server sibling, rebuild, restart (keeps DB)
#   ./scripts/bootstrap.sh --maintenance        # safe prune only (NO volumes)
#   ./scripts/bootstrap.sh --build api ...      # rebuild and restart only selected services
#   (Available services: api, bacnet-server, bacnet-scraper, caddy, db, fdd-loop, frontend, grafana [--with-grafana], host-stats, mosquitto [--with-mqtt-bridge], weather-scraper)
#   ./scripts/bootstrap.sh --frontend          # before start: stop frontend, remove frontend node_modules volume (fresh npm install on next up)
#
# When to re-bootstrap for frontend:
#   Frontend code (React/TS) changes are picked up by hot reload (npm run dev in container); no re-bootstrap needed.
#   Use --frontend only if you changed package.json and need a fresh npm install in the container.
#   Use --build frontend if you need the container image rebuilt with latest code (e.g. no hot reload).
#
# Site maintenance (pull both repos, prune, rebuild, verify):
#   ./scripts/bootstrap.sh --maintenance --update --verify
#
# Notes:
# First run (--with-mqtt-bridge): starts the stack with the MQTT broker and bridge (writes env, compose up with mqtt profile, migrations, bootstrap complete).
# ./scripts/bootstrap.sh --with-mqtt-bridge && ./scripts/bootstrap.sh --verify --test
#
# Second run (--verify --test): only verifies services and then runs the test suite (frontend lint+typecheck+vitest, backend pytest, Caddy). It does not start the stack again.
# ./scripts/bootstrap.sh --with-mqtt-bridge && ./scripts/bootstrap.sh --test
#
# Verify + tests	./scripts/bootstrap.sh --verify --test
# Verify only	./scripts/bootstrap.sh --verify
# Tests only	./scripts/bootstrap.sh --test
#
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
STACK_DIR="$REPO_ROOT/stack"

# -----------------------------
# Flags / defaults
# -----------------------------
VERIFY_ONLY=false
VERIFY_CODE=false
MINIMAL=false
RESET_GRAFANA=false
RESET_DATA=false
WITH_GRAFANA=false
BUILD_ALL=false
UPDATE_PULL_REBUILD=false
MAINTENANCE_ONLY=false
INSTALL_DOCKER=false
SKIP_DOCKER_INSTALL=false
NO_AUTH=false
FRONTEND_RESET=false
WITH_MQTT_BRIDGE=false

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
    --test) VERIFY_CODE=true ;;
    --minimal) MINIMAL=true ;;
    --reset-grafana) RESET_GRAFANA=true ;;
    --with-grafana) WITH_GRAFANA=true ;;
    --with-mqtt-bridge) WITH_MQTT_BRIDGE=true ;;
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
    --no-auth) NO_AUTH=true ;;
    --frontend) FRONTEND_RESET=true ;;
    -h|--help)
      cat <<EOF
Usage: $0 [options]

Core:
  (no args)                 Build + start full stack (ALL services)
  --minimal                 Start minimal stack (db, bacnet-server, bacnet-scraper; use --with-grafana to add Grafana)
  --with-grafana            Include Grafana in the stack (default: not installed)
  --with-mqtt-bridge        Enable BACnet2MQTT bridge + start MQTT broker (localhost:1883) for Home Assistant on same box
  --verify                  Show running services + health checks (exits before starting stack; run --with-mqtt-bridge without --verify first to enable bridge)
  --verify --test           Verify services then run tests; then exit
  --test                    Run tests only: frontend (lint + typecheck + vitest), backend (pytest), Caddy validate; then exit (no E2E/Selenium)
  --update                  Git pull open-fdd + diy-bacnet-server (sibling), rebuild, restart (keeps DB)
  --maintenance             Safe Docker prune only (NO volumes)

  Site maintenance:  $0 --maintenance --update --verify

Build controls:
  --build SERVICE ...       Rebuild + restart only these services, then exit
                           Services: api, bacnet-server, bacnet-scraper, caddy, db, fdd-loop, frontend, grafana, host-stats, mosquitto (--with-mqtt-bridge), weather-scraper
  --build-all               Rebuild + restart all services, then exit
  --frontend                Before start: stop frontend, remove frontend node_modules volume (fresh npm install on next up; use after package.json changes)

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

Security:
  --no-auth                 Do not generate or set OFDD_API_KEY (API will not require Bearer auth). Default: generate key and write to stack/.env.

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

  # Secure-by-default: generate OFDD_API_KEY if not set (unless --no-auth)
  if ! $NO_AUTH; then
    if ! grep -qE '^OFDD_API_KEY=.+' "$env_file" 2>/dev/null; then
      local new_key=""
      if have_cmd openssl; then
        new_key=$(openssl rand -hex 32 2>/dev/null)
      fi
      if [[ -z "$new_key" ]] && have_cmd python3; then
        new_key=$(python3 -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null)
      fi
      if [[ -z "$new_key" ]]; then
        echo "Warning: could not generate OFDD_API_KEY (install openssl or use Python 3). API will run without auth."
      else
        if grep -q "^OFDD_API_KEY=" "$env_file" 2>/dev/null; then
          sed "${sed_i[@]}" "s|^OFDD_API_KEY=.*|OFDD_API_KEY=${new_key}|" "$env_file"
        else
          echo "OFDD_API_KEY=${new_key}" >> "$env_file"
        fi
        echo ""
        echo "Generated OFDD_API_KEY=${new_key}"
        echo "Use this key for API auth (e.g. Authorization: Bearer <key>)."
        echo ""
      fi
    fi
  fi

  # BACnet2MQTT bridge: set defaults only when --with-mqtt-bridge and not already set
  if $WITH_MQTT_BRIDGE; then
    for entry in "BACNET2MQTT_ENABLED=true" "MQTT_BROKER_URL=mqtt://127.0.0.1:1883" "HA_DISCOVERY_ENABLED=true"; do
      key="${entry%%=*}"
      if ! grep -qE "^${key}=" "$env_file" 2>/dev/null; then
        echo "$entry" >> "$env_file"
      fi
    done
  fi
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
    echo "  → Start stack: ./scripts/bootstrap.sh  (or: cd STACK && $(docker_compose_cmd) up -d db)"
  fi

  if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx openfdd_grafana; then
    echo "Grafana: running — http://localhost:3000 (or via Caddy /grafana when started with --with-grafana)"
  else
    echo "Grafana: not running — start with: ./scripts/bootstrap.sh --with-grafana"
  fi

  if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx openfdd_mosquitto; then
    echo "MQTT:     localhost:1883 (broker running; BACnet2MQTT bridge if enabled in bacnet-server env)"
  elif grep -qE '^BACNET2MQTT_ENABLED=true' "$STACK_DIR/.env" 2>/dev/null; then
    echo "MQTT:     broker not running — start stack with: ./scripts/bootstrap.sh --with-mqtt-bridge (without --verify)"
  fi

  echo ""
  echo "=== Feature checks (BACnet + API, up to 5 tries / 10s apart) ==="
  if curl_retry 5 10 -X POST http://localhost:8080/server_hello -H "Content-Type: application/json" \
      -d '{"jsonrpc":"2.0","id":"0","method":"server_hello","params":{}}'; then
    echo "BACnet: http://localhost:8080 (OK — server_hello responded)"
    hello="$(curl -sf -X POST http://localhost:8080/server_hello -H "Content-Type: application/json" \
      -d '{"jsonrpc":"2.0","id":"0","method":"server_hello","params":{}}' 2>/dev/null)" || true
    if echo "$hello" | grep -q '"mqtt_bridge"'; then
      if echo "$hello" | grep -q '"connected":true'; then
        echo "MQTT bridge: connected to broker"
      else
        echo "MQTT bridge: enabled but disconnected (check broker and bacnet-server logs)"
      fi
    fi
  else
    echo "BACnet: http://localhost:8080 (not reachable or no response after 5 tries)"
  fi

  if curl_retry 5 10 http://localhost:8000/health; then
    echo "API:    http://localhost:8000 (OK — /health responded)"
  else
    echo "API:    http://localhost:8000 (not reachable after 5 tries; run full stack without --minimal)"
  fi

  echo ""
  echo "=== Weather data check (GET /sites, /points, POST /download/csv) ==="
  if [[ -x "$REPO_ROOT/scripts/curl_weather_data.sh" ]]; then
    if (cd "$REPO_ROOT" && ./scripts/curl_weather_data.sh http://localhost:8000 >/dev/null 2>&1); then
      echo "Weather: OK (Open-Meteo points present for site; Web weather page will show charts)."
    else
      echo "Weather: no Open-Meteo points yet (run FDD or weather scraper; Config → open_meteo_site_id = your site name)."
    fi
  else
    echo "Weather: skip (scripts/curl_weather_data.sh not executable)."
  fi
  echo ""
}

# --test scope: frontend lint + typecheck + vitest (unit); backend pytest (open_fdd/tests/); Caddy validate.
# Does not run E2E Selenium (scripts/e2e_frontend_selenium.py) or long-running tests (e.g. long_term_bacnet_scrape_test).
# Backend runs with OFDD_API_KEY unset so tests use no-auth app.
verify_code() {
  local failed=0
  echo "=== Tests: frontend (lint + typecheck + vitest), backend (pytest), Caddy ==="
  echo ""

  # Frontend: lint + tsc + vitest. Prefer frontend container so host does not need npm.
  if [[ -d "$REPO_ROOT/frontend" ]]; then
    echo "--- Frontend (lint + typecheck + unit tests) ---"
    local frontend_ok=true
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx openfdd_frontend; then
      if docker exec openfdd_frontend sh -c "cd /app && npm run lint && npx tsc -b --noEmit && npm run test"; then
        echo "Frontend: OK (via container)"
      else
        echo "Frontend: FAIL (container: docker exec openfdd_frontend sh -c 'cd /app && npm run lint && npx tsc -b --noEmit && npm run test')"
        frontend_ok=false
      fi
    elif (cd "$REPO_ROOT/frontend" && npm run lint 2>/dev/null && npx tsc -b --noEmit 2>/dev/null && npm run test 2>/dev/null); then
      echo "Frontend: OK (via host npm)"
    else
      echo "Frontend: FAIL (start stack so openfdd_frontend runs, or: cd frontend && npm install && npm run lint && npx tsc -b --noEmit && npm run test)"
      frontend_ok=false
    fi
    $frontend_ok || failed=1
    echo ""
  else
    echo "--- Frontend: skip (no frontend dir) ---"
    echo ""
  fi

  # Backend: pytest (use .venv if present). Unset OFDD_API_KEY so test client gets no-auth app.
  echo "--- Backend (pytest) ---"
  local py=
  if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
    py="$REPO_ROOT/.venv/bin/python"
  else
    py="python3"
  fi
  if (cd "$REPO_ROOT" && unset OFDD_API_KEY OFDD_CADDY_INTERNAL_SECRET && $py -m pytest open_fdd/tests/ -v --tb=short); then
    echo "Backend: OK"
  else
    echo "Backend: FAIL or skipped (install: pip install -e \".[dev]\" then run: unset OFDD_API_KEY && pytest open_fdd/tests/ -v)"
    failed=1
  fi
  echo ""

  # Caddy: validate Caddyfile
  echo "--- Caddy (validate Caddyfile) ---"
  if docker run --rm -v "$STACK_DIR/caddy/Caddyfile:/etc/caddy/Caddyfile:ro" caddy:2 caddy validate --config /etc/caddy/Caddyfile; then
    echo "Caddy: OK"
  else
    echo "Caddy: FAIL (Caddyfile invalid or docker unavailable)"
    failed=1
  fi
  echo ""

  if [[ $failed -eq 0 ]]; then
    echo "All checks passed."
  else
    echo "Some checks failed."
    return 1
  fi
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
  local curl_auth=()
  [[ -n "${OFDD_API_KEY:-}" ]] && curl_auth=(-H "Authorization: Bearer $OFDD_API_KEY")
  API_BASE="${OFDD_API_URL:-http://localhost:8000}"
  API_BASE="${API_BASE%/}"

  # If we already have sites, set open_meteo_site_id to the first site's name so weather goes there (Web weather page).
  local open_meteo_site_id_override=""
  local sites_json
  sites_json="$(curl -sf -H "Accept: application/json" "${curl_auth[@]}" "$API_BASE/sites" 2>/dev/null)" || true
  if [[ -n "$sites_json" ]]; then
    open_meteo_site_id_override=$(echo "$sites_json" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    sites = d if isinstance(d, list) else []
    if sites and sites[0].get('name'):
        print(sites[0]['name'])
except Exception:
    pass
" 2>/dev/null)
  fi

  local body
  body=$(OPEN_METEO_SITE_ID_OVERRIDE="$open_meteo_site_id_override" python3 -c "
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
om_site = os.environ.get('OPEN_METEO_SITE_ID_OVERRIDE') or os.environ.get('OFDD_OPEN_METEO_SITE_ID', 'default')
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
    'open_meteo_site_id': om_site,
    'graph_sync_interval_min': env('OFDD_GRAPH_SYNC_INTERVAL_MIN', 5),
}))
" 2>/dev/null) || body="{\"rule_interval_hours\":0.1,\"lookback_days\":3,\"rules_dir\":\"analyst/rules\",\"brick_ttl_dir\":\"config\",\"bacnet_enabled\":true,\"bacnet_scrape_interval_min\":1,\"bacnet_server_url\":\"http://localhost:8080\",\"bacnet_site_id\":\"default\",\"open_meteo_enabled\":true,\"open_meteo_interval_hours\":24,\"open_meteo_latitude\":41.88,\"open_meteo_longitude\":-87.63,\"open_meteo_timezone\":\"America/Chicago\",\"open_meteo_days_back\":3,\"open_meteo_site_id\":\"default\",\"graph_sync_interval_min\":5}"

  if curl -sf -X PUT "$API_BASE/config" -H "Content-Type: application/json" "${curl_auth[@]}" -d "$body" >/dev/null 2>&1; then
    echo "  PUT /config OK (config stored in RDF)."
    [[ -n "$open_meteo_site_id_override" ]] && echo "  open_meteo_site_id set to first site: $open_meteo_site_id_override"
  else
    echo "  PUT /config failed (non-fatal; set config via API or /app/ later)."
    return 1
  fi

  # Trigger one FDD run so weather is fetched and points created (Web weather page will have data).
  if curl -sf -X POST "$API_BASE/run-fdd" -H "Content-Type: application/json" "${curl_auth[@]}" -d '{}' >/dev/null 2>&1; then
    echo "  POST /run-fdd OK (FDD loop will run soon; weather points created for open_meteo_site_id)."
  else
    echo "  POST /run-fdd skipped or failed (weather will appear after next FDD run or weather scraper)."
  fi
  return 0
}

reset_data_via_api() {
  if ! wait_for_api; then
    echo "Skip --reset-data (API not reachable)."
    return 1
  fi

  local curl_auth=()
  [[ -n "${OFDD_API_KEY:-}" ]] && curl_auth=(-H "Authorization: Bearer $OFDD_API_KEY")
  local sites_json ids
  sites_json="$(curl -sf -H "Accept: application/json" "${curl_auth[@]}" "$API_BASE/sites" 2>/dev/null)" || {
    echo "GET /sites failed."
    return 1
  }

  ids="$(echo "$sites_json" | grep -o '"id":"[^"]*"' | sed 's/"id":"//;s/"$//')"

  if [[ -n "$ids" ]]; then
    while IFS= read -r id; do
      [[ -z "$id" ]] && continue
      if curl -sf -X DELETE "$API_BASE/sites/$id" "${curl_auth[@]}" >/dev/null 2>&1; then
        echo "  Deleted site $id"
      else
        echo "  Failed to delete site $id"
      fi
    done <<< "$ids"
  else
    echo "  No sites to delete."
  fi

  if curl -sf -X POST "$API_BASE/data-model/reset" -H "Content-Type: application/json" "${curl_auth[@]}" -d '{}' >/dev/null 2>&1; then
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

    for f in $(ls -1 sql/*.sql | sort); do
      echo " - Applying: $f"

      if [[ "$(basename "$f")" == "007_retention.sql" ]]; then
        sed "s/365 days/${RETENTION_DAYS} days/g" "$f" | \
          $dc exec -T db psql -U postgres -d openfdd -v ON_ERROR_STOP=1 -f - || true
      else
        $dc exec -T db psql -U postgres -d openfdd -v ON_ERROR_STOP=1 -f - < "$f" || true
      fi
    done
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
  if $VERIFY_CODE; then
    verify_code || exit 1
  fi
  exit 0
fi

if $VERIFY_CODE; then
  check_prereqs
  verify_code || exit 1
  exit 0
fi

if $MAINTENANCE_ONLY && ! $UPDATE_PULL_REBUILD; then
  check_prereqs
  safe_docker_prune
  exit 0
fi

# From here on, we run stack operations (default/no args = FULL stack)
write_edge_env
# Reload stack/.env so OFDD_API_KEY (and others) are available for seed_config_via_api and compose
[[ -f "$STACK_DIR/.env" ]] && set -a && source "$STACK_DIR/.env" 2>/dev/null; set +a
check_prereqs
ensure_diy_bacnet_sibling

dc="$(docker_compose_cmd)"
DC_PROFILE=()
$WITH_GRAFANA && DC_PROFILE+=(--profile grafana)
$WITH_MQTT_BRIDGE && DC_PROFILE+=(--profile mqtt)

# -----------------------------
# --frontend: stop frontend, remove node_modules volume (fresh npm install on next up)
# -----------------------------
if $FRONTEND_RESET; then
  echo "=== Frontend reset: stop frontend, remove node_modules volume ==="
  (cd "$STACK_DIR" && $dc stop frontend 2>/dev/null) || true
  vol="$(docker volume ls -q | grep frontend_node_modules | head -1)"
  if [[ -n "$vol" ]]; then
    docker volume rm "$vol" || true
    echo "Removed volume: $vol (next up will run fresh npm install)."
  else
    echo "No frontend_node_modules volume found (nothing to remove)."
  fi
fi

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
  $dc --profile grafana stop grafana 2>/dev/null || true
  $dc --profile grafana rm -f grafana 2>/dev/null || true
  vol="$(docker volume ls -q | grep grafana_data | head -1 || true)"
  [[ -n "${vol:-}" ]] && docker volume rm "$vol" || true
  echo "Starting Grafana with fresh provisioning..."
  $dc --profile grafana up -d grafana
  echo "Done. Open http://localhost:3000 (admin/admin). Use --with-grafana on next full bootstrap to include Grafana."
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
  # Caddy has no image build (uses image: caddy:2); restart so it reloads Caddyfile when included.
  if echo " $BUILD_SERVICES_STR " | grep -q " caddy "; then
    $dc restart caddy
    echo "Caddy restarted (reloads Caddyfile)."
  fi
  echo "Done. Services restarted: $BUILD_SERVICES_STR"
  if $WITH_MQTT_BRIDGE; then
    echo "  MQTT:     localhost:1883 (BACnet2MQTT bridge enabled; use HA MQTT integration to discover entities)"
  fi
  exit 0
fi

# -----------------------------
# Default run (NO ARGS): FULL STACK
# -----------------------------
# Ensure bridge env vars are in stack/.env so bacnet-server gets them (server_hello will show mqtt_bridge)
if $WITH_MQTT_BRIDGE; then
  env_file="$STACK_DIR/.env"
  for entry in "BACNET2MQTT_ENABLED=true" "MQTT_BROKER_URL=mqtt://127.0.0.1:1883" "HA_DISCOVERY_ENABLED=true"; do
    key="${entry%%=*}"
    if ! grep -qE "^${key}=" "$env_file" 2>/dev/null; then
      echo "$entry" >> "$env_file"
    fi
  done
fi

cd "$STACK_DIR"

if $MINIMAL; then
  echo "=== Starting minimal stack (DB + BACnet server + scraper) ==="
  if $WITH_GRAFANA; then
    $dc "${DC_PROFILE[@]}" up -d --build db bacnet-server bacnet-scraper grafana
  else
    $dc "${DC_PROFILE[@]}" up -d --build db bacnet-server bacnet-scraper
  fi
else
  echo "=== Building and starting full stack ==="
  $dc "${DC_PROFILE[@]}" up -d --build
fi

# So bacnet-server picks up bridge env (server_hello returns mqtt_bridge)
if $WITH_MQTT_BRIDGE; then
  $dc "${DC_PROFILE[@]}" up -d --force-recreate bacnet-server
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
echo '  DB:       localhost:5432/openfdd  (postgres/postgres)'
if $WITH_GRAFANA; then
  echo '  Grafana:  http://localhost:3000   (admin/admin) or via Caddy /grafana'
fi
if $WITH_MQTT_BRIDGE || grep -qE '^BACNET2MQTT_ENABLED=true' "$STACK_DIR/.env" 2>/dev/null; then
  echo "  MQTT:     localhost:1883 (BACnet2MQTT bridge enabled; use HA MQTT integration to discover entities)"
fi
if $MINIMAL; then
  echo "  BACnet:   http://localhost:8080   (diy-bacnet-server Swagger)"
  echo "  (Minimal: raw BACnet data only. No FDD, no weather, no API. Add Grafana with --with-grafana.)"
else
  echo "  API:      http://localhost:8000   (docs: /docs)"
  echo "  Frontend: http://localhost:5173   (or via Caddy http://localhost)"
  echo "  BACnet:   http://localhost:8080   (diy-bacnet-server Swagger)"
  echo "  (Grafana not started by default. Use --with-grafana to include it.)"
fi
echo ""
echo "Verify all services: ./scripts/bootstrap.sh --verify"
echo "View logs: $(docker_compose_cmd) -f stack/docker-compose.yml logs -f"
echo ""