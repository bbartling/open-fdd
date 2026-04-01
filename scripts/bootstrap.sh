#!/usr/bin/env bash
#
# open-fdd bootstrap: full Docker stack — DB, BACnet server, BACnet scraper,
# weather scraper, FDD loop, host-stats, API, Caddy.
# ./scripts/bootstrap.sh --reset-data && ./scripts/bootstrap.sh --test
# Default behavior (no args):
#   ./scripts/bootstrap.sh
#     -> builds and starts the FULL stack (Grafana and MQTT broker are NOT started by default)
#
# Optional add-ons:
#   --with-grafana       TimescaleDB charts at http://localhost:3000 (see docs)
#   --with-mqtt-bridge   Mosquitto on :1883 + BACnet2MQTT env (experimental / future remote collection—not required for core Open-FDD)
#   --with-mcp-rag       Optional MCP RAG service on :8090 (derived docs retrieval + optional guarded API tools)
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
# Frontend serving mode:
#   Stack frontend runs a production build (npm run build + static serve), not Vite dev/HMR.
#   Each frontend container start runs npm run build (dist is on the bind-mounted repo).
#
# Site maintenance (pull both repos, prune, rebuild, verify):
#   ./scripts/bootstrap.sh --maintenance --update --verify
#   --verify here is HTTP health only (BACnet server_hello, API /health), not pytest.
#   Pull latest PyPI deps for diy-bacnet-server (e.g. bacpypes3): add --force-rebuild so Docker
#   rebuilds images even when git HEAD did not change.
# Full maintenance + pytest + optional DIY server tests in container:
#   ./scripts/bootstrap.sh --maintenance --update --verify --force-rebuild --test --diy-bacnet-tests
# Heavy ops example (pull, rebuild, verify, tests, app user, frontend volume reset, self-signed Caddy):
#   printf '%s' 'YOUR_PASSWORD' | ./scripts/bootstrap.sh --maintenance --update --verify --force-rebuild --test --diy-bacnet-tests --user ben --password-stdin --frontend --caddy-self-signed
#
# Day 1 after git clone (full stack + self-signed HTTPS on Caddy; no tests, no --frontend, no git pull):
#   ./scripts/bootstrap.sh --caddy-self-signed
# Same with Phase-1 UI login (password on stdin):
#   printf '%s' 'YOUR_PASSWORD' | ./scripts/bootstrap.sh --user YOURNAME --password-stdin --caddy-self-signed
#
# Optional hostname for cert CN/SAN: add --caddy-tls-cn my.machine.local
# Revert Caddy to HTTP-only on :80: ./scripts/bootstrap.sh --caddy-http-only
# Notes:
# First MQTT enable: ./scripts/bootstrap.sh --with-mqtt-bridge   (then verify / test as needed)
# Verify + tests	./scripts/bootstrap.sh --verify --test
# Verify only	./scripts/bootstrap.sh --verify
# Tests only	./scripts/bootstrap.sh --test
# Update then tests (same run): ./scripts/bootstrap.sh --update --test
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
MODE="full"
MODE_EXPLICIT=false
RESET_GRAFANA=false
RESET_DATA=false
WITH_GRAFANA=false
WITH_MQTT_BRIDGE=false
WITH_MCP_RAG=false
BUILD_ALL=false
UPDATE_PULL_REBUILD=false
UPDATE_FORCE_REBUILD=false
MAINTENANCE_ONLY=false
DIY_BACNET_TESTS=false
INSTALL_DOCKER=false
SKIP_DOCKER_INSTALL=false
NO_AUTH=false
APP_USER="${OFDD_APP_USER:-}"
APP_PASSWORD="${OFDD_APP_PASSWORD:-}"
APP_PASSWORD_FILE=""
APP_PASSWORD_STDIN=false
FRONTEND_RESET=false
CADDY_SELF_SIGNED=false
CADDY_HTTP_ONLY=false
CADDY_TLS_CN="${CADDY_TLS_CN:-openfdd.local}"
RETENTION_DAYS=365
LOG_MAX_SIZE="100m"
LOG_MAX_FILES=3

# Allow env overrides from stack/.env (if present)
if [[ -f "$STACK_DIR/.env" ]]; then
  # shellcheck source=/dev/null
  set +e
  set -a
  source "$STACK_DIR/.env" 2>/dev/null
  env_source_rc=$?
  set +a
  set -e
  if [[ $env_source_rc -ne 0 ]]; then
    echo "Warning: could not fully parse $STACK_DIR/.env; continuing with defaults/CLI flags."
  fi
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
    --mode)
      i=$(( i + 1 ))
      if [[ $i -ge ${#args[@]} ]]; then
        echo "--mode requires one of: full, collector, model, engine"
        exit 1
      fi
      MODE="${args[$i]}"
      MODE_EXPLICIT=true
      ;;
    --reset-grafana) RESET_GRAFANA=true ;;
    --with-grafana) WITH_GRAFANA=true ;;
    --with-mqtt-bridge) WITH_MQTT_BRIDGE=true ;;
    --with-mcp-rag) WITH_MCP_RAG=true ;;
    --reset-data) RESET_DATA=true ;;
    --build-all) BUILD_ALL=true ;;
    --update) UPDATE_PULL_REBUILD=true ;;
    --force-rebuild) UPDATE_FORCE_REBUILD=true ;;
    --maintenance) MAINTENANCE_ONLY=true ;;
    --diy-bacnet-tests) DIY_BACNET_TESTS=true ;;
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
    --user) i=$(( i + 1 )); [[ $i -lt ${#args[@]} ]] && APP_USER="${args[$i]}" ;;
    --password-file) i=$(( i + 1 )); [[ $i -lt ${#args[@]} ]] && APP_PASSWORD_FILE="${args[$i]}" ;;
    --password-stdin) APP_PASSWORD_STDIN=true ;;
    --frontend) FRONTEND_RESET=true ;;
    --caddy-self-signed) CADDY_SELF_SIGNED=true ;;
    --caddy-http-only) CADDY_HTTP_ONLY=true ;;
    --caddy-tls-cn)
      i=$(( i + 1 ))
      if [[ $i -ge ${#args[@]} ]]; then
        echo "--caddy-tls-cn requires a hostname (e.g. openfdd.lab)."
        exit 1
      fi
      CADDY_TLS_CN="${args[$i]}"
      ;;
    -h|--help)
      cat <<EOF
Usage: $0 [options]

Core:
  (no args)                 Build + start full stack (ALL services; Grafana/MQTT off unless flags below)
  --minimal                 Start minimal stack (db, bacnet-server, bacnet-scraper; add --with-grafana for Grafana)
  --mode MODE              Partial deployment mode: full, collector, model, engine (default: full)
  --with-grafana            Include Grafana (http://localhost:3000; optional SQL dashboards)
  --with-mqtt-bridge        Start Mosquitto + wire BACnet2MQTT env (experimental; future remote/MQTT use—not core product yet)
  --with-mcp-rag            Include MCP RAG service (http://localhost:8090; retrieval over docs/text + optional guarded API tools)
  --verify                  Show running services + health checks (exits before starting stack)
  --verify --test           Verify services then run tests; then exit
  --test                    Run tests only: frontend (lint + typecheck + vitest), backend (pytest), Caddy validate; then exit (no E2E/Selenium)
  --update                  Git pull open-fdd + diy-bacnet-server (sibling), rebuild, restart (keeps DB)
  --force-rebuild           With --update: always docker compose build (refreshes unpinned pip deps e.g. bacpypes3 even if git unchanged)
  --maintenance             Safe Docker prune only (NO volumes)
  --diy-bacnet-tests        With --test (or after --update --test): run pytest in openfdd_bacnet_server against /app/tests

  Site maintenance:  $0 --maintenance --update --verify

Build controls:
  --build SERVICE ...       Rebuild + restart only these services, then exit
                           Services: api, bacnet-server, bacnet-scraper, caddy, db, fdd-loop, frontend, grafana, host-stats, mcp-rag, mosquitto, weather-scraper
  --build-all               Rebuild + restart all services, then exit
  --frontend                Before start: stop frontend, remove frontend node_modules volume (fresh npm install on next up; use after package.json changes)

Data / ops:
  --reset-grafana           Wipe Grafana volume and restart Grafana (re-apply provisioning)
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
  --caddy-self-signed       Self-signed TLS for Caddy (:443, :80→HTTPS); writes certs; stack/.env: OPENFDD_CADDYFILE, OFDD_TRUST_FORWARDED_PROTO=true, BACNET_SWAGGER_SERVERS_URL=/bacnet (HTTPS gateway UI at https://HOST/bacnet/docs)
  --caddy-tls-cn HOST       With --caddy-self-signed: certificate CN/SAN (default: openfdd.local)
  --caddy-http-only         Turn off self-signed Caddy mode (default HTTP Caddyfile on :80 only; OFDD_TRUST_FORWARDED_PROTO=false)
  --user NAME               Configure Phase-1 app login user (writes hash config into stack/.env).
  --password-file PATH      Read Phase-1 app password from file (first line).
  --password-stdin          Read Phase-1 app password from stdin.
                            (Alternative: set OFDD_APP_PASSWORD env var.)

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

if [[ "$MODE" != "full" && "$MODE" != "collector" && "$MODE" != "model" && "$MODE" != "engine" ]]; then
  echo "Invalid --mode '$MODE'. Use: full, collector, model, engine."
  exit 1
fi
if $MINIMAL; then
  MODE="collector"
fi

# --update --test: defer pytest to after pull/rebuild (otherwise the early --test handler exits before --update runs).
RUN_TESTS_AFTER_UPDATE=false
if $UPDATE_PULL_REBUILD && $VERIFY_CODE; then
  RUN_TESTS_AFTER_UPDATE=true
  VERIFY_CODE=false
fi

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
  if ! docker ps >/dev/null 2>&1; then
    echo "Docker is installed, but this user cannot access the Docker daemon."
    echo "  - Try: sudo docker ps"
    echo "  - If that works, add your user to the docker group and log in again:"
    echo "      sudo usermod -aG docker \$USER"
    echo "    Then log out and back in (or run: newgrp docker)."
    echo "  - Check: docker -v && docker compose version && groups"
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
    # diy-bacnet-server RPC Bearer (BACNET_RPC_API_KEY in compose); Open-FDD uses this on outbound RPC.
    if ! grep -qE '^OFDD_BACNET_SERVER_API_KEY=.+' "$env_file" 2>/dev/null; then
      local bac_key=""
      if have_cmd openssl; then
        bac_key=$(openssl rand -hex 32 2>/dev/null)
      fi
      if [[ -z "$bac_key" ]] && have_cmd python3; then
        bac_key=$(python3 -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null)
      fi
      if [[ -n "$bac_key" ]]; then
        if grep -q "^OFDD_BACNET_SERVER_API_KEY=" "$env_file" 2>/dev/null; then
          sed "${sed_i[@]}" "s|^OFDD_BACNET_SERVER_API_KEY=.*|OFDD_BACNET_SERVER_API_KEY=${bac_key}|" "$env_file"
        else
          echo "OFDD_BACNET_SERVER_API_KEY=${bac_key}" >> "$env_file"
        fi
        echo ""
        echo "Generated OFDD_BACNET_SERVER_API_KEY=${bac_key}"
        echo "diy-bacnet-server expects this as Bearer (BACNET_RPC_API_KEY in compose). Gateway Swagger: Authorize → paste this token."
        echo ""
      fi
    fi
  fi

  # BACnet2MQTT: append defaults when --with-mqtt-bridge and keys not already in stack/.env
  if $WITH_MQTT_BRIDGE; then
    ensure_mqtt_bridge_env_defaults "$env_file"
  fi

  # MCP RAG action tools are off by default (retrieval remains enabled).
  if ! grep -qE '^OFDD_MCP_ENABLE_ACTION_TOOLS=' "$env_file" 2>/dev/null; then
    echo "OFDD_MCP_ENABLE_ACTION_TOOLS=false" >> "$env_file"
  fi

  # Optional Phase-1 app user auth file.
  write_auth_env_if_requested
}

write_auth_env_if_requested() {
  local auth_file="$STACK_DIR/.env"
  # If --no-auth is requested, remove all auth entries and stop.
  if $NO_AUTH; then
    local sed_i=(-i)
    if sed --version >/dev/null 2>&1; then
      sed_i=(-i)
    else
      sed_i=(-i "")
    fi
    for key in OFDD_APP_USER OFDD_APP_USER_HASH OFDD_JWT_SECRET OFDD_ACCESS_TOKEN_MINUTES OFDD_REFRESH_TOKEN_DAYS OFDD_API_KEY OFDD_BACNET_SERVER_API_KEY; do
      sed "${sed_i[@]}" "/^${key}=/d" "$auth_file" 2>/dev/null || true
    done
    return 0
  fi
  if [[ -z "${APP_USER:-}" && -z "${APP_PASSWORD:-}" && -z "${APP_PASSWORD_FILE:-}" ]] && ! $APP_PASSWORD_STDIN; then
    return 0
  fi
  if [[ -z "${APP_USER:-}" ]]; then
    echo "--user is required when configuring app login auth."
    exit 1
  fi
  if [[ -z "${APP_PASSWORD:-}" ]]; then
    if [[ -n "${APP_PASSWORD_FILE:-}" ]]; then
      if [[ ! -f "$APP_PASSWORD_FILE" ]]; then
        echo "--password-file not found: $APP_PASSWORD_FILE"
        exit 1
      fi
      IFS= read -r APP_PASSWORD < "$APP_PASSWORD_FILE" || true
    elif $APP_PASSWORD_STDIN; then
      IFS= read -r APP_PASSWORD || true
    else
      read -sr -p "Password for user '$APP_USER': " APP_PASSWORD
      echo ""
    fi
  fi
  if [[ -z "${APP_PASSWORD:-}" ]]; then
    echo "Password is empty; refusing to write auth config."
    exit 1
  fi
  local py="${REPO_ROOT}/.venv/bin/python"
  [[ -x "$py" ]] || py="python3"
  if ! have_cmd "$py"; then
    echo "python3 not found; cannot generate password hash for auth env."
    exit 1
  fi
  local hash jwt_secret
  hash="$(
    OFDD_TMP_PASSWORD="$APP_PASSWORD" "$py" -c "from argon2 import PasswordHasher; import os; print(PasswordHasher().hash(os.environ['OFDD_TMP_PASSWORD']))" 2>/dev/null
  )"
  if [[ -z "${hash:-}" ]]; then
    echo "Could not generate argon2 password hash (install argon2-cffi in this python env)."
    exit 1
  fi
  jwt_secret="$($py -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null)"
  [[ -n "$jwt_secret" ]] || jwt_secret="openfdd-change-me-$(date +%s)"
  shell_quote() {
    local raw="$1"
    raw="${raw//\'/\'\"\'\"\'}"
    printf "'%s'" "$raw"
  }
  local q_user q_hash q_jwt
  q_user="$(shell_quote "$APP_USER")"
  q_hash="$(shell_quote "$hash")"
  q_jwt="$(shell_quote "$jwt_secret")"
  local sed_i=(-i)
  if sed --version >/dev/null 2>&1; then
    sed_i=(-i)
  else
    sed_i=(-i "")
  fi
  for kv in \
    "OFDD_APP_USER=${q_user}" \
    "OFDD_APP_USER_HASH=${q_hash}" \
    "OFDD_JWT_SECRET=${q_jwt}" \
    "OFDD_ACCESS_TOKEN_MINUTES=60" \
    "OFDD_REFRESH_TOKEN_DAYS=7"; do
    local key="${kv%%=*}"
    if grep -q "^${key}=" "$auth_file" 2>/dev/null; then
      sed "${sed_i[@]}" "s|^${key}=.*|${kv}|" "$auth_file"
    else
      echo "$kv" >> "$auth_file"
    fi
  done
  chmod 600 "$auth_file" 2>/dev/null || true
  echo "Wrote Phase-1 auth config keys in: $auth_file (user: $APP_USER)"
}

ensure_mqtt_bridge_env_defaults() {
  local env_file="$1"
  [[ -f "$env_file" ]] || touch "$env_file"

  for entry in "BACNET2MQTT_ENABLED=true" "MQTT_BROKER_URL=mqtt://127.0.0.1:1883" "HA_DISCOVERY_ENABLED=true"; do
    local key="${entry%%=*}"
    if ! grep -qE "^${key}=" "$env_file" 2>/dev/null; then
      echo "$entry" >> "$env_file"
    fi
  done
}

env_file_set_kv() {
  local env_file="$1" key="$2" val="$3"
  [[ -f "$env_file" ]] || touch "$env_file"
  local sed_i=(-i)
  if sed --version >/dev/null 2>&1; then
    sed_i=(-i)
  else
    sed_i=(-i "")
  fi
  if grep -q "^${key}=" "$env_file" 2>/dev/null; then
    sed "${sed_i[@]}" "s|^${key}=.*|${key}=${val}|" "$env_file"
  else
    echo "${key}=${val}" >> "$env_file"
  fi
}

disable_caddy_self_signed_config() {
  local env_file="$STACK_DIR/.env"
  [[ -f "$env_file" ]] || return 0
  local sed_i=(-i)
  if sed --version >/dev/null 2>&1; then
    sed_i=(-i)
  else
    sed_i=(-i "")
  fi
  sed "${sed_i[@]}" "/^OPENFDD_CADDYFILE=/d" "$env_file" 2>/dev/null || true
  sed "${sed_i[@]}" "/^BACNET_SWAGGER_SERVERS_URL=/d" "$env_file" 2>/dev/null || true
  env_file_set_kv "$env_file" "OFDD_TRUST_FORWARDED_PROTO" "false"
  echo "Caddy: reverted to default HTTP-only entry (removed OPENFDD_CADDYFILE; OFDD_TRUST_FORWARDED_PROTO=false; removed BACNET_SWAGGER_SERVERS_URL if present)."
}

ensure_caddy_self_signed_tls() {
  local env_file="$STACK_DIR/.env"
  local cert_dir="$STACK_DIR/caddy/certs"
  if ! have_cmd openssl; then
    echo "openssl not found; install it to use --caddy-self-signed."
    exit 1
  fi
  mkdir -p "$cert_dir"
  local cn="${CADDY_TLS_CN:-openfdd.local}"
  echo "=== Self-signed TLS for Caddy (CN/SAN: $cn) → $cert_dir ==="
  if openssl req -x509 -newkey rsa:4096 \
    -keyout "$cert_dir/key.pem" \
    -out "$cert_dir/cert.pem" \
    -days 365 -nodes \
    -subj "/CN=${cn}" \
    -addext "subjectAltName=DNS:${cn},DNS:localhost,IP:127.0.0.1" 2>/dev/null; then
    :
  else
    echo "(openssl -addext unsupported; generating cert without explicit SAN extension)"
    openssl req -x509 -newkey rsa:4096 \
      -keyout "$cert_dir/key.pem" \
      -out "$cert_dir/cert.pem" \
      -days 365 -nodes \
      -subj "/CN=${cn}"
  fi
  chmod 600 "$cert_dir/key.pem" 2>/dev/null || true
  env_file_set_kv "$env_file" "OPENFDD_CADDYFILE" "./caddy/Caddyfile.selfsigned"
  env_file_set_kv "$env_file" "OFDD_TRUST_FORWARDED_PROTO" "true"
  env_file_set_kv "$env_file" "BACNET_SWAGGER_SERVERS_URL" "/bacnet"
  chmod 600 "$env_file" 2>/dev/null || true
  echo "stack/.env: OPENFDD_CADDYFILE=./caddy/Caddyfile.selfsigned, OFDD_TRUST_FORWARDED_PROTO=true, BACNET_SWAGGER_SERVERS_URL=/bacnet"
  echo "Use https://localhost/ (browser warns). :80 redirects to HTTPS."
  echo "Operators: use https://localhost/ → BACnet tools (no Swagger required). Dev/advanced: https://localhost/bacnet/docs or :8080 on host."
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

# When stack/.env selects Caddyfile.selfsigned: curl HTTPS edge (not raw :8000 / :8080).
verify_tls_caddy_smoke() {
  local base="https://127.0.0.1"
  local tmp h code
  tmp="$(mktemp)" || return 0
  echo "=== TLS / Caddy edge smoke (curl -k) ==="
  echo "UI must load via https://THIS_HOST/ so /api and /auth go through Caddy. http://HOST:5173 alone has no API proxy — login will fail."
  echo ""

  if curl -sk -o "$tmp" -w "%{http_code}" "$base/api/health" | grep -qx 200; then
    if grep -q '"status"' "$tmp" 2>/dev/null; then
      echo "OK   $base/api/health (Open-FDD API over TLS)"
    else
      echo "WARN $base/api/health returned 200 but not JSON health (unexpected body)"
    fi
  else
    code="$(curl -sk -o "$tmp" -w "%{http_code}" "$base/api/health" || true)"
    echo "FAIL $base/api/health (HTTP $code; need Caddy on 443 + api healthy)"
  fi

  code="$(curl -sk -o "$tmp" -w "%{http_code}" "$base/" || true)"
  if [[ "$code" == "200" ]] && grep -qE '<div id="root"|</html>' "$tmp" 2>/dev/null; then
    echo "OK   $base/ (frontend HTML over TLS)"
  else
    echo "FAIL $base/ (HTTP $code; expected HTML shell)"
  fi

  if curl -sk -o "$tmp" -w "%{http_code}" \
    -X POST "$base/bacnet/server_hello" \
    -H "Content-Type: application/json" \
    -d '{"jsonrpc":"2.0","id":"0","method":"server_hello","params":{}}' | grep -qx 200; then
    if grep -q '"result"' "$tmp" 2>/dev/null; then
      echo "OK   $base/bacnet/server_hello (diy-bacnet over TLS path /bacnet)"
    else
      echo "WARN $base/bacnet/server_hello — 200 but unexpected body"
    fi
  else
    code="$(curl -sk -o "$tmp" -w "%{http_code}" \
      -X POST "$base/bacnet/server_hello" \
      -H "Content-Type: application/json" \
      -d '{"jsonrpc":"2.0","id":"0","method":"server_hello","params":{}}' || true)"
    echo "FAIL $base/bacnet/server_hello (HTTP $code)"
  fi

  code="$(curl -sk -o "$tmp" -w "%{http_code}" -X POST "$base/api/auth/login" \
    -H "Content-Type: application/json" \
    -d '{"username":"__bootstrap_probe__","password":"wrong"}' || true)"
  if [[ "$code" == "401" ]] && grep -q 'UNAUTHORIZED\|"code"' "$tmp" 2>/dev/null; then
    echo "OK   $base/api/auth/login wrong password → 401 (route reaches API through Caddy)"
  elif [[ "$code" == "503" ]]; then
    echo "WARN $base/api/auth/login → 503 (app user auth not configured? use --user / --password-stdin)"
  else
    echo "FAIL $base/api/auth/login (HTTP $code; expected 401 JSON for bad password — if HTML, you are not hitting the API via Caddy)"
  fi

  local api_key bacnet_key
  api_key=""
  bacnet_key=""
  [[ -f "$STACK_DIR/.env" ]] && api_key="$(grep -E '^OFDD_API_KEY=' "$STACK_DIR/.env" 2>/dev/null | cut -d= -f2- | tr -d '\r')" || true
  [[ -f "$STACK_DIR/.env" ]] && bacnet_key="$(grep -E '^OFDD_BACNET_SERVER_API_KEY=' "$STACK_DIR/.env" 2>/dev/null | cut -d= -f2- | tr -d '\r')" || true
  api_key="${api_key#\"}"; api_key="${api_key%\"}"
  bacnet_key="${bacnet_key#\"}"; bacnet_key="${bacnet_key%\"}"

  if [[ -n "$api_key" ]]; then
    code="$(curl -sk -o /dev/null -w "%{http_code}" "$base/api/sites" || true)"
    if [[ "$code" == "401" ]]; then
      echo "OK   GET $base/api/sites without Bearer → 401 (OFDD_API_KEY enforced on edge)"
    else
      echo "WARN GET $base/api/sites without Bearer → HTTP $code (expected 401 when OFDD_API_KEY set)"
    fi
    code="$(curl -sk -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $api_key" "$base/api/sites" || true)"
    if [[ "$code" == "200" ]]; then
      echo "OK   GET $base/api/sites with Bearer (machine API key) → 200"
    else
      echo "WARN GET $base/api/sites with Bearer → HTTP $code (expected 200)"
    fi
  else
    echo "SKIP machine Bearer check (OFDD_API_KEY empty in stack/.env)"
  fi

  if [[ -n "$bacnet_key" ]]; then
    code="$(curl -sk -o /dev/null -w "%{http_code}" -X POST "$base/bacnet/client_read_property" \
      -H "Content-Type: application/json" -d '{}' || true)"
    if [[ "$code" == "401" ]]; then
      echo "OK   POST $base/bacnet/client_read_property without Bearer → 401 (BACNET_RPC_API_KEY enforced)"
    else
      echo "WARN POST .../client_read_property without Bearer → HTTP $code (expected 401 when key set)"
    fi
    code="$(curl -sk -o /dev/null -w "%{http_code}" -X POST "$base/bacnet/client_read_property" \
      -H "Content-Type: application/json" -H "Authorization: Bearer $bacnet_key" -d '{}' || true)"
    if [[ "$code" != "401" ]] && [[ "$code" != "403" ]]; then
      echo "OK   POST .../client_read_property with Bearer → HTTP $code (auth accepted; 422/400 expected for empty body)"
    else
      echo "WARN POST .../client_read_property with Bearer → HTTP $code (expected not 401/403 when key matches)"
    fi
  else
    echo "SKIP diy BACnet Bearer check (OFDD_BACNET_SERVER_API_KEY empty)"
  fi

  h="$(curl -skI "$base/api/health" | tr -d '\r' || true)"
  if echo "$h" | grep -qi '^strict-transport-security:'; then
    echo "OK   HSTS present on $base/api/health response"
  else
    echo "WARN No HSTS header on API response (Caddy may not add it on this path)"
  fi

  rm -f "$tmp"
  echo ""
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
    echo "Grafana: running — http://localhost:3000 (optional; started with --with-grafana)"
  else
    echo "Grafana: not running — optional: ./scripts/bootstrap.sh --with-grafana"
  fi

  if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx openfdd_mosquitto; then
    echo "MQTT broker: localhost:1883 (optional; experimental BACnet2MQTT path)"
  elif grep -qE '^BACNET2MQTT_ENABLED=true' "$STACK_DIR/.env" 2>/dev/null; then
    echo "MQTT: BACnet2MQTT enabled in .env but broker not running — start with: ./scripts/bootstrap.sh --with-mqtt-bridge"
  fi

  if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx openfdd_mcp_rag; then
    echo "MCP RAG: running — http://localhost:8090 (manifest: /manifest)"
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
    echo "Weather: skip (scripts/curl_weather_data.sh missing or not executable)."
  fi

  if grep -qE '^OPENFDD_CADDYFILE=.*Caddyfile\.selfsigned' "$STACK_DIR/.env" 2>/dev/null; then
    echo "=== Caddy (self-signed HTTPS) ==="
    if curl_retry 3 5 -k -sf "https://localhost/" >/dev/null 2>&1; then
      echo "Caddy: https://localhost/ (OK — use -k with curl; browser will show cert warning)"
    else
      echo "Caddy: https://localhost/ not responding yet (stack still starting or port 443 blocked)"
    fi
    verify_tls_caddy_smoke
  fi
  echo ""
}

ensure_docs_text_and_rag_index() {
  local py
  if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
    py="$REPO_ROOT/.venv/bin/python"
  else
    py="python3"
    if ! have_cmd "$py"; then
      echo "python3 not found; skipping MCP docs/index build."
      return 0
    fi
  fi

  if [[ ! -f "$REPO_ROOT/pdf/open-fdd-docs.txt" ]]; then
    echo "=== Building docs text for MCP RAG ==="
    (cd "$REPO_ROOT" && "$py" scripts/build_docs_pdf.py --no-pdf) || true
  fi

  echo "=== Building MCP RAG index ==="
  (cd "$REPO_ROOT" && "$py" scripts/build_mcp_rag_index.py) || true
}

# --test scope: frontend lint + typecheck + vitest (unit); backend pytest (open_fdd/tests/); Caddy validate.
# Does not run E2E Selenium (scripts/e2e_frontend_selenium.py) or long-running tests (e.g. long_term_bacnet_scrape_test).
# Backend runs with OFDD_API_KEY unset so tests use no-auth app.
verify_code() {
  local failed=0
  echo "=== Tests for mode '$MODE': frontend (lint + typecheck + vitest), backend (pytest), Caddy ==="
  echo ""

  # Frontend checks are only required for full/model modes.
  if [[ -d "$REPO_ROOT/frontend" ]] && [[ "$MODE" == "full" || "$MODE" == "model" ]]; then
    echo "--- Frontend (lint + typecheck + unit tests) ---"
    local frontend_ok=true
    local frontend_running=false
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx openfdd_frontend; then
      frontend_running=true
    else
      # If host npm is missing, auto-start frontend container so --test is truly one command.
      if ! have_cmd npm; then
        echo "Frontend container not running; starting frontend service for tests..."
        local dc
        dc="$(docker_compose_cmd)"
        if (cd "$STACK_DIR" && $dc up -d frontend >/dev/null 2>&1); then
          if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx openfdd_frontend; then
            frontend_running=true
          fi
        fi
      fi
    fi
    if $frontend_running; then
      # Ensure new frontend deps are present when package.json changed.
      # Use explicit workdir to avoid OCI cwd-namespace issues on some hosts.
      if (cd / && docker exec -w /app openfdd_frontend sh -lc "npm install && npm run lint && npx tsc -b --noEmit && npm run test"); then
        echo "Frontend: OK (via container)"
      else
        echo "Frontend container test path failed; attempting host npm fallback..."
        if have_cmd npm && (cd "$REPO_ROOT/frontend" && npm install && npm run lint && npx tsc -b --noEmit && npm run test); then
          echo "Frontend: OK (via host npm fallback)"
        else
          echo "Frontend: FAIL (container and host fallback failed)"
          echo "  Container cmd: docker exec -w /app openfdd_frontend sh -lc 'npm install && npm run lint && npx tsc -b --noEmit && npm run test'"
          echo "  Host cmd:      cd frontend && npm install && npm run lint && npx tsc -b --noEmit && npm run test"
          frontend_ok=false
        fi
      fi
    elif (cd "$REPO_ROOT/frontend" && npm run lint 2>/dev/null && npx tsc -b --noEmit 2>/dev/null && npm run test 2>/dev/null); then
      echo "Frontend: OK (via host npm)"
    else
      if ! have_cmd npm; then
        echo "Frontend: FAIL (npm not installed and frontend container unavailable)."
        echo "Run one of:"
        echo "  1) ./scripts/bootstrap.sh   # starts stack incl. openfdd_frontend"
        echo "  2) sudo apt install npm && cd frontend && npm install"
      else
        echo "Frontend: FAIL (start stack so openfdd_frontend runs, or: cd frontend && npm install && npm run lint && npx tsc -b --noEmit && npm run test)"
      fi
      frontend_ok=false
    fi
    $frontend_ok || failed=1
    echo ""
  else
    echo "--- Frontend: skip (no frontend dir) ---"
    echo ""
  fi

  # Backend tests vary by module mode (full = full suite).
  echo "--- Backend (pytest) ---"
  local py=
  if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
    py="$REPO_ROOT/.venv/bin/python"
  else
    py="python3"
  fi
  local pytest_target="open_fdd/tests/"
  if [[ "$MODE" == "collector" ]]; then
    pytest_target="open_fdd/tests/platform/test_bacnet_driver.py open_fdd/tests/platform/test_bacnet_api.py"
  elif [[ "$MODE" == "model" ]]; then
    pytest_target="open_fdd/tests/platform/test_data_model_api.py open_fdd/tests/platform/test_data_model_ttl.py open_fdd/tests/platform_api/test_model_context.py"
  elif [[ "$MODE" == "engine" ]]; then
    pytest_target="open_fdd/tests/engine/"
  fi

  if (cd "$REPO_ROOT" && unset OFDD_API_KEY OFDD_CADDY_INTERNAL_SECRET OFDD_APP_USER OFDD_APP_USER_HASH OFDD_JWT_SECRET OFDD_ACCESS_TOKEN_MINUTES OFDD_REFRESH_TOKEN_DAYS && $py -m pytest $pytest_target -v --tb=short); then
    echo "Backend: OK"
  else
    echo "Backend: FAIL or skipped."
    echo "  Fix: from repo root create a venv and install dev deps (pytest is in [project.optional-dependencies].dev):"
    echo "    python3 -m venv .venv && . .venv/bin/activate && pip install -U pip && pip install -e \".[dev]\""
    echo "  This script uses .venv/bin/python when present; otherwise it falls back to python3 (often missing pytest)."
    echo "  Manual rerun: cd \"$REPO_ROOT\" && unset OFDD_API_KEY OFDD_CADDY_INTERNAL_SECRET && $py -m pytest $pytest_target -v --tb=short"
    failed=1
  fi
  echo ""

  # Caddy is validated only when interface layer is expected.
  if [[ "$MODE" != "collector" && "$MODE" != "engine" ]]; then
  echo "--- Caddy (validate Caddyfile) ---"
  if docker run --rm -v "$STACK_DIR/caddy/Caddyfile:/etc/caddy/Caddyfile:ro" caddy:2 caddy validate --config /etc/caddy/Caddyfile; then
    echo "Caddy: OK (default Caddyfile)"
  else
    echo "Caddy: FAIL (Caddyfile invalid or docker unavailable)"
    failed=1
  fi
  if [[ -f "$STACK_DIR/caddy/Caddyfile.selfsigned" ]] && have_cmd openssl; then
    local tmpc
    tmpc="$(mktemp -d)"
    if openssl req -x509 -newkey rsa:2048 -keyout "$tmpc/key.pem" -out "$tmpc/cert.pem" -days 1 -nodes \
      -subj "/CN=validate.local" -addext "subjectAltName=DNS:localhost" 2>/dev/null \
      || openssl req -x509 -newkey rsa:2048 -keyout "$tmpc/key.pem" -out "$tmpc/cert.pem" -days 1 -nodes \
        -subj "/CN=validate.local"; then
      if docker run --rm \
        -v "$STACK_DIR/caddy/Caddyfile.selfsigned:/etc/caddy/Caddyfile:ro" \
        -v "$tmpc:/etc/caddy/certs:ro" \
        caddy:2 caddy validate --config /etc/caddy/Caddyfile; then
        echo "Caddy: OK (Caddyfile.selfsigned + dummy certs)"
      else
        echo "Caddy: FAIL (Caddyfile.selfsigned invalid or docker unavailable)"
        failed=1
      fi
    fi
    rm -rf "$tmpc"
  fi
  echo ""
  fi

  if [[ $failed -eq 0 ]]; then
    echo "All checks passed."
  else
    echo "Some checks failed."
    return 1
  fi
}

verify_code_for_mode() {
  local selected_mode="$1"
  local prev_mode="$MODE"
  MODE="$selected_mode"
  verify_code
  local rc=$?
  MODE="$prev_mode"
  return $rc
}

# Pytest suite shipped with diy-bacnet-server (container has /app/tests after COPY).
# Checks the container image, not the host venv (Open-FDD pytest uses .venv on the host separately).
run_diy_bacnet_tests() {
  echo "--- DIY BACnet server container (pytest tests/) ---"
  if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -qx openfdd_bacnet_server; then
    echo "DIY BACnet tests: skip (openfdd_bacnet_server not running)."
    return 0
  fi
  if ! docker exec openfdd_bacnet_server sh -lc 'test -d /app/tests'; then
    echo "DIY BACnet tests: FAIL — /app/tests not found in openfdd_bacnet_server (rebuild bacnet-server from diy-bacnet-server context)."
    return 1
  fi
  if ! docker exec openfdd_bacnet_server sh -lc 'python3 -c "import pytest" 2>/dev/null'; then
    echo "DIY BACnet tests: FAIL — pytest not importable in openfdd_bacnet_server (pip install dev/test deps in the DIY image)."
    return 1
  fi
  if docker exec openfdd_bacnet_server sh -lc "cd /app && python3 -m pytest tests/ -q --tb=short"; then
    echo "DIY BACnet container tests: OK"
  else
    echo "DIY BACnet container tests: FAIL (pytest ran; see output above)."
    echo "  Manual: docker exec -w /app openfdd_bacnet_server python3 -m pytest tests/ -v --tb=short"
    return 1
  fi
}

run_optional_diy_bacnet_tests() {
  $DIY_BACNET_TESTS || return 0
  run_diy_bacnet_tests || return 1
}

run_verify_code_matrix_or_single() {
  if ! $MODE_EXPLICIT && [[ "$MODE" == "full" ]]; then
    echo "=== Running modular test matrix (collector, model, engine, full) ==="
    local matrix_failed=0
    for m in collector model engine full; do
      echo ""
      echo ">>> MODE: $m"
      if ! verify_code_for_mode "$m"; then
        matrix_failed=1
      fi
    done
    [[ $matrix_failed -eq 0 ]] || return 1
  else
    verify_code || return 1
  fi
  return 0
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
    'rules_dir': os.environ.get('OFDD_RULES_DIR', 'stack/rules'),
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
" 2>/dev/null) || body="{\"rule_interval_hours\":0.1,\"lookback_days\":3,\"rules_dir\":\"stack/rules\",\"brick_ttl_dir\":\"config\",\"bacnet_enabled\":true,\"bacnet_scrape_interval_min\":1,\"bacnet_server_url\":\"http://localhost:8080\",\"bacnet_site_id\":\"default\",\"open_meteo_enabled\":true,\"open_meteo_interval_hours\":24,\"open_meteo_latitude\":41.88,\"open_meteo_longitude\":-87.63,\"open_meteo_timezone\":\"America/Chicago\",\"open_meteo_days_back\":3,\"open_meteo_site_id\":\"default\",\"graph_sync_interval_min\":5}"

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
  run_verify_code_matrix_or_single || exit 1
  run_optional_diy_bacnet_tests || exit 1
  exit 0
fi

if $MAINTENANCE_ONLY && ! $UPDATE_PULL_REBUILD; then
  check_prereqs
  safe_docker_prune
  exit 0
fi

# From here on, we run stack operations (default/no args = FULL stack)
write_edge_env

if $CADDY_SELF_SIGNED && $CADDY_HTTP_ONLY; then
  echo "Choose at most one of --caddy-self-signed and --caddy-http-only."
  exit 1
fi
if $CADDY_HTTP_ONLY; then
  disable_caddy_self_signed_config
elif $CADDY_SELF_SIGNED; then
  ensure_caddy_self_signed_tls
fi

# Reload stack/.env so OFDD_API_KEY (and others) are available for seed_config_via_api and compose
if [[ -f "$STACK_DIR/.env" ]]; then
  set +e
  set -a
  source "$STACK_DIR/.env" 2>/dev/null
  env_source_rc=$?
  set +a
  set -e
  if [[ $env_source_rc -ne 0 ]]; then
    echo "Warning: could not fully parse $STACK_DIR/.env after write_edge_env."
  fi
fi

check_prereqs
ensure_diy_bacnet_sibling

dc="$(docker_compose_cmd)"
DC_PROFILE=()
$WITH_GRAFANA && DC_PROFILE+=(--profile grafana)
$WITH_MQTT_BRIDGE && DC_PROFILE+=(--profile mqtt)
$WITH_MCP_RAG && DC_PROFILE+=(--profile mcp-rag)

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
  if ! $UPDATE_FORCE_REBUILD; then
    if [[ -n "$PRE_OPENFDD" && -n "$POST_OPENFDD" && "$PRE_OPENFDD" == "$POST_OPENFDD" ]] && \
       [[ -n "$PRE_BACNET" && -n "$POST_BACNET" && "$PRE_BACNET" == "$POST_BACNET" ]]; then
      SKIP_BUILD=true
    fi
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
  fi
  if $RUN_TESTS_AFTER_UPDATE; then
    echo ""
    echo "=== Post-update tests (--test) ==="
    run_verify_code_matrix_or_single || exit 1
    run_optional_diy_bacnet_tests || exit 1
  fi
  if ! $VERIFY_ONLY && ! $RUN_TESTS_AFTER_UPDATE; then
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
    echo "  MQTT:     localhost:1883 (experimental BACnet2MQTT; for future remote/MQTT workflows)"
  fi
  exit 0
fi

# -----------------------------
# Default run (NO ARGS): FULL STACK
# -----------------------------
# Ensure bridge env vars are in stack/.env so bacnet-server gets them (server_hello will show mqtt_bridge)
if $WITH_MQTT_BRIDGE; then
  ensure_mqtt_bridge_env_defaults "$STACK_DIR/.env"
fi
if $WITH_MCP_RAG; then
  ensure_docs_text_and_rag_index
fi

cd "$STACK_DIR"

if [[ "$MODE" == "collector" ]]; then
  echo "=== Starting collector mode (DB + BACnet server + scraper) ==="
  svc="db bacnet-server bacnet-scraper"
  $WITH_GRAFANA && svc="$svc grafana"
  $dc "${DC_PROFILE[@]}" up -d --build $svc
elif [[ "$MODE" == "model" ]]; then
  echo "=== Starting model mode (DB + API + frontend + caddy) ==="
  $dc "${DC_PROFILE[@]}" up -d --build db api frontend caddy
elif [[ "$MODE" == "engine" ]]; then
  echo "=== Starting engine mode (DB + FDD + weather loop) ==="
  $dc "${DC_PROFILE[@]}" up -d --build db fdd-loop weather-scraper
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

if [[ "$MODE" == "full" || "$MODE" == "model" ]]; then
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
  echo "  MQTT:     localhost:1883 (experimental; BACnet2MQTT for future remote collection—not core Open-FDD yet)"
fi
if $WITH_MCP_RAG; then
  echo "  MCP RAG:  http://localhost:8090 (manifest: /manifest; health: /health)"
fi
if [[ "$MODE" == "collector" ]]; then
  echo "  BACnet:   http://localhost:8080   (gateway HTTP; integrators / BACnet tools in full stack use Open-FDD UI)"
  echo "  (Collector mode: raw BACnet data path. No API/FDD unless explicitly started.)"
elif [[ "$MODE" == "model" ]]; then
  echo "  API:      http://localhost:8000   (docs: /docs)"
  echo "  Frontend: http://localhost:5173   (or via Caddy http://localhost)"
  if grep -qE '^OPENFDD_CADDYFILE=.*Caddyfile\.selfsigned' "$STACK_DIR/.env" 2>/dev/null; then
    echo "  Self-signed TLS: use https://localhost/ for the UI (not :5173 alone). BACnet + CRUD: web app; optional dev OpenAPI https://localhost/api/docs"
  fi
  echo "  (Model mode: knowledge graph and CRUD workflows.)"
elif [[ "$MODE" == "engine" ]]; then
  echo "  (Engine mode: FDD and weather loops with DB. No API/frontend by default.)"
else
  echo "  API:      http://localhost:8000   (docs: /docs)"
  echo "  Frontend: http://localhost:5173   (or via Caddy http://localhost)"
  echo "  BACnet:   http://localhost:8080   (gateway; operators use web UI → BACnet tools)"
  if grep -qE '^OPENFDD_CADDYFILE=.*Caddyfile\.selfsigned' "$STACK_DIR/.env" 2>/dev/null; then
    echo ""
    echo "  Self-signed TLS: open the app at https://localhost/ (or https://THIS_HOST/) — not :5173 alone."
    echo "  Optional dev OpenAPI (TLS): https://localhost/api/docs  |  gateway https://localhost/bacnet/docs"
    echo "  Direct ports (HTTP, automation): :8000 API, :8080 gateway, :5173 static (no /api proxy)."
  fi
  echo "  (Grafana not started by default. Use --with-grafana to include it.)"
fi
echo ""
echo "Verify all services: ./scripts/bootstrap.sh --verify"
echo "View logs: $(docker_compose_cmd) -f stack/docker-compose.yml logs -f"
echo ""