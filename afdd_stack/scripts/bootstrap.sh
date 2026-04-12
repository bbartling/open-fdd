#!/usr/bin/env bash
#
# Open-FDD — bootstrap: VOLTTRON via official Docker (volttron-docker) + optional local Timescale for SQL schema.
#
# Field data: VOLTTRON pub/sub + historian (see VOLTTRON Central / platform historian SQL driver).
# Open-FDD engine + faults: run as VOLTTRON agents against time-series tables; helpers in openfdd_stack.volttron_bridge.
#
# Defaults (Chicago, IL — override with env):
#   OFDD_DEFAULT_TZ=America/Chicago
#   OFDD_DEFAULT_LAT / OFDD_DEFAULT_LON — Open-Meteo / platform (match config.py defaults)
#   OFDD_VOLTTRON_CERT_COUNTRY=US  OFDD_VOLTTRON_CERT_STATE=IL  OFDD_VOLTTRON_CERT_LOCALITY=Chicago
#     (certificate prompts inside the container / vcfg — VOLTTRON has no single "site location" key in config)
#
# Env:
#   OFDD_VOLTTRON_DOCKER_DIR  volttron-docker clone (default: $HOME/volttron-docker)
#   OFDD_VOLTTRON_DOCKER_REPO Official compose/image repo (default: https://github.com/VOLTTRON/volttron-docker.git)
#   OFDD_VOLTTRON_ROLE    central | edge (default: central). Edge stub adds volttron-central-address.
#   OFDD_VOLTTRON_CENTRAL_WEB  Edge only: Central URL (default: http://127.0.0.1:8443)
#   OFDD_PG_HOST / OFDD_DB_DSN — DB checks and openfdd-defaults.env
#   OFDD_VOLTTRON_LOG_DIR — log directory for host-mounted VOLTTRON_HOME (logrotate fragment)
#   OFDD_VOLTTRON_CONFIG_STRICT=1 — do not auto-quarantine duplicate web-ssl-* lines in $VOLTTRON_HOME/config
#   OFDD_FORWARD_CONFIG_OUT — required for --write-forward-historian-config-template (absolute path to JSON)
#   OFDD_FORWARD_CENTRAL_VIP — destination-vip for that template (default tcp://127.0.0.1:22916)
#   OFDD_VOLTTRON_DOCKER_SERVICE — docker compose service name for exec hints (default volttron1)
#   OFDD_VOLTTRON_AUTH_CREDENTIALS — for --volttron-docker-auth-add (sensitive; export in shell only)
#   OFDD_VOLTTRON_REMOTE_USER_ID — for --volttron-docker-auth-remote-approve
#   OFDD_VOLTTRON_CONFIG_MAX_LINES — for --volttron-docker-show-config (default 120)
#   OFDD_VOLTTRON_LOG_LINES / OFDD_VOLTTRON_LOG_GREP — for --volttron-docker-tail-logs
#   OFDD_VOLTTRON_LAB_SKIP_PUSH=1 — --volttron-docker-lab-up skips copying lab templates first
#   OFDD_VOLTTRON_LAB_NO_BACKUP=1 — --volttron-docker-lab-push overwrites without *.bak.* copies
#   OFDD_VOLTTRON_DOCKER_DOWN_VOLUMES=1 — --volttron-docker-lab-down passes docker compose down -v
#   OFDD_COMPOSE_DB_MAX_WAIT — seconds to wait for pg_isready after up -d db (default 90)
#
# Quick start (from open-fdd repo root):
#   ./scripts/bootstrap.sh --central-lab
#   # Minimal Central + SQLHistorian (templates + compose + psycopg2; no manual docker exec):
#   LOCAL_USER_ID=$(id -u) ./scripts/bootstrap.sh --volttron-docker-lab-up
#   # Or build the image and: ./scripts/volttron-docker.sh up -d
#
# Optional UI + Central prep (still from repo root):
#   ./scripts/bootstrap.sh --build-openfdd-ui
#   ./scripts/bootstrap.sh --write-openfdd-ui-agent-config
#   ./scripts/bootstrap.sh --volttron-config-stub
#   ./scripts/bootstrap.sh --print-vcfg-hints
#   ./scripts/bootstrap.sh --print-forward-historian-cheatsheet
#   ./scripts/bootstrap.sh --print-volttron-central-sql-forward-poc
#
# Local verification (no Docker services required for pytest):
#   ./scripts/bootstrap.sh --test
#   OFDD_BOOTSTRAP_INSTALL_DEV=1 ./scripts/bootstrap.sh --test   # pip install -e ".[dev]" first
#   OFDD_BOOTSTRAP_FRONTEND_TEST=1 ./scripts/bootstrap.sh --test  # also npm lint + vitest (needs Node)
#
set -euo pipefail

# Avoid indefinite hangs on slow networks (override in environment if needed).
export PIP_DEFAULT_TIMEOUT="${PIP_DEFAULT_TIMEOUT:-120}"
export COMPOSE_HTTP_TIMEOUT="${COMPOSE_HTTP_TIMEOUT:-120}"
# Docker CLI (pull/image resolution); helps "stuck" compose on bad networks.
export DOCKER_CLIENT_TIMEOUT="${DOCKER_CLIENT_TIMEOUT:-180}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AFDD_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
STACK_DIR="$AFDD_ROOT/stack"
REPO_ROOT="$(cd "$AFDD_ROOT/.." && pwd)"

VOLTTRON_DOCKER_DIR="${OFDD_VOLTTRON_DOCKER_DIR:-$HOME/volttron-docker}"
VOLTTRON_DOCKER_REPO="${OFDD_VOLTTRON_DOCKER_REPO:-https://github.com/VOLTTRON/volttron-docker.git}"

# Chicago, IL defaults (platform + vcfg certificate prompts)
DEFAULT_TZ="${OFDD_DEFAULT_TZ:-America/Chicago}"
DEFAULT_LAT="${OFDD_DEFAULT_LAT:-41.88}"
DEFAULT_LON="${OFDD_DEFAULT_LON:--87.63}"
CERT_COUNTRY="${OFDD_VOLTTRON_CERT_COUNTRY:-US}"
CERT_STATE="${OFDD_VOLTTRON_CERT_STATE:-IL}"
CERT_LOCALITY="${OFDD_VOLTTRON_CERT_LOCALITY:-Chicago}"
VOLTTRON_ROLE="${OFDD_VOLTTRON_ROLE:-central}"
CENTRAL_WEB="${OFDD_VOLTTRON_CENTRAL_WEB:-http://127.0.0.1:8443}"
PG_HOST="${OFDD_PG_HOST:-127.0.0.1}"
DB_DSN="${OFDD_DB_DSN:-postgresql://postgres:postgres@${PG_HOST}:5432/openfdd}"

DOCTOR=false
PRINT_PATHS=false
COMPOSE_DB=false
BUILD_OPENFDD_UI=false
WRITE_OPENFDD_UI_AGENT_CONFIG=false
VOLTTRON_CONFIG_STUB=false
PRINT_VCFG_HINTS=false
WRITE_ENV_DEFAULTS=false
WRITE_LOGROTATE=false
VERIFY_FDD_SCHEMA=false
SMOKE_FDD_LOOP=false
CENTRAL_LAB=false
VOLTTRON_DOCKER=false
TEST=false
PRINT_FORWARD_HISTORIAN_CHEATSHEET=false
WRITE_FORWARD_HISTORIAN_CONFIG_TEMPLATE=false
PRINT_VOLTTRON_CENTRAL_SQL_FORWARD_POC=false
VOLTTRON_DOCKER_SERVERKEY=false
VOLTTRON_DOCKER_SHOW_CONFIG=false
VOLTTRON_DOCKER_CAT_CONFIG=false
VOLTTRON_DOCKER_AUTH_REMOTE_LIST=false
VOLTTRON_DOCKER_AUTH_REMOTE_APPROVE=false
VOLTTRON_DOCKER_AUTH_ADD=false
VOLTTRON_DOCKER_TAIL_LOGS=false
VOLTTRON_DOCKER_LAB_PUSH=false
VOLTTRON_DOCKER_LAB_UP=false
VOLTTRON_DOCKER_LAB_DOWN=false
VOLTTRON_DOCKER_INSTALL_PG_DRIVER=false
VOLTTRON_DOCKER_AGENTS=false
VOLTTRON_DOCKER_AGENT_STATUS=false
VOLTTRON_DOCKER_BASH=false
VOLTTRON_DOCKER_COMPOSE=false
declare -a VOLTTRON_DOCKER_COMPOSE_ARGS=()

usage() {
  cat <<'EOF'
Open-FDD bootstrap (VOLTTRON in Docker via volttron-docker)

Entry point: run from repo root as ./scripts/bootstrap.sh (thin wrapper over afdd_stack/scripts/bootstrap.sh).

Usage:
  ./scripts/bootstrap.sh --help

Typical flow (from open-fdd repo root):
  ./scripts/bootstrap.sh --central-lab
  LOCAL_USER_ID=$(id -u) ./scripts/bootstrap.sh --volttron-docker-lab-up
  # Or: ./scripts/volttron-docker.sh up -d  (compose in OFDD_VOLTTRON_DOCKER_DIR; build image if needed)

Options:
  --doctor              Check git, python3, Docker, monorepo paths
  --volttron-docker     Clone or update volttron-docker into OFDD_VOLTTRON_DOCKER_DIR (default ~/volttron-docker)
  --clone-volttron-docker
                        Same as --volttron-docker (alias)
  --print-paths         Print export PYTHONPATH=... for openfdd_stack (host dev / agents)
  --compose-db          docker compose -f afdd_stack/stack/docker-compose.yml up -d db (Timescale + openfdd SQL)
  --build-openfdd-ui    npm ci + vite build (afdd_stack/frontend); use VITE_BASE_PATH=/openfdd/ for Central subpath
  --write-openfdd-ui-agent-config
                        Write afdd_stack/volttron_agents/openfdd_central_ui/agent-config.json → frontend/dist
  --volttron-config-stub
                        If $VOLTTRON_HOME/config is missing, write [volttron] stub (mount this dir as VOLTTRON_HOME in Docker)
  --write-env-defaults  Write $VOLTTRON_HOME/openfdd-defaults.env (TZ, OFDD_*, DB DSN, PYTHONPATH for Open-FDD on host)
  --write-logrotate     Write $VOLTTRON_HOME/logrotate-openfdd-volttron.conf (when logs live on the host)
  --verify-fdd-schema   psql or docker exec: assert FDD tables exist (fault_definitions, fault_results, fdd_run_log, …)
  --smoke-fdd-loop      One-shot run_fdd_loop() (needs DB + pip install -e ".[stack]" or PYTHONPATH from --print-paths)
  --print-vcfg-hints    Certificate defaults + volttron-docker / Central notes
  --print-forward-historian-cheatsheet
                        Print Edge→Central ForwardHistorian auth + log commands (see docs/howto/edge_forward_historian_to_central.md)
  --write-forward-historian-config-template
                        Write JSON template for ForwardHistorian (requires OFDD_FORWARD_CONFIG_OUT=/abs/path.json;
                        optional OFDD_FORWARD_CENTRAL_VIP default tcp://127.0.0.1:22916; serverkey is PLACEHOLDER)
  --print-volttron-central-sql-forward-poc
                        Print SQL-forward lab goals + cheatsheet pointer + docker log one-liners + Central agent hygiene note
  --volttron-docker-serverkey
                        Same key as inside the container: docker exec -itu volttron volttron1 bash → vctl auth serverkey (non-interactive)
  --volttron-docker-bash
                        Interactive: docker exec -itu volttron <service> bash (replaces this shell; type exit to leave)
  --volttron-docker-show-config
                        docker exec: print first N lines of \$VOLTTRON_HOME/config (OFDD_VOLTTRON_CONFIG_MAX_LINES default 120)
  --volttron-docker-cat-config
                        docker exec: cat full \$VOLTTRON_HOME/config (same as in-container: cat \$VOLTTRON_HOME/config)
  --volttron-docker-auth-remote-list
                        docker exec: vctl auth remote list (pending edge registrations)
  --volttron-docker-auth-remote-approve
                        docker exec: vctl auth remote approve (requires OFDD_VOLTTRON_REMOTE_USER_ID from the list)
  --volttron-docker-auth-add
                        docker exec: vctl auth add --credentials (requires OFDD_VOLTTRON_AUTH_CREDENTIALS, e.g. edge forwarder pubkey)
  --volttron-docker-tail-logs
                        docker exec: tail volttron.log (OFDD_VOLTTRON_LOG_LINES default 200; optional OFDD_VOLTTRON_LOG_GREP=egrep pattern)
  --volttron-docker-lab-push
                        Copy minimal Central+SQLHistorian lab files from afdd_stack/scripts/volttron_docker_lab/ into OFDD_VOLTTRON_DOCKER_DIR (backs up targets unless OFDD_VOLTTRON_LAB_NO_BACKUP=1)
  --volttron-docker-lab-up
                        Lab push (unless OFDD_VOLTTRON_LAB_SKIP_PUSH=1) + docker compose up -d + wait for container + install PostgreSQL driver in image (eclipsevolttron often lacks psycopg2)
  --volttron-docker-lab-down
                        docker compose down in OFDD_VOLTTRON_DOCKER_DIR (add OFDD_VOLTTRON_DOCKER_DOWN_VOLUMES=1 for down -v)
  --volttron-docker-install-pg-driver
                        docker exec (root): pip install psycopg2-binary for SQLHistorian→Postgres in the running container
  --volttron-docker-agents
                        docker exec: vctl list (running agents)
  --volttron-docker-agent-status
                        docker exec: vctl status
  --volttron-docker-compose
                        Run docker compose in OFDD_VOLTTRON_DOCKER_DIR; must be LAST flag — remaining args are passed through (e.g. --volttron-docker-compose ps | logs -f volttron1 | down)
  --central-lab         One shot: --compose-db + wait for Postgres + --volttron-config-stub + --write-env-defaults
                        + --write-logrotate + --verify-fdd-schema + --volttron-docker + printed next steps
  --test                Run pytest (open_fdd/tests + afdd_stack/openfdd_stack/tests) from repo root; optional frontend
                        when OFDD_BOOTSTRAP_FRONTEND_TEST=1 (npm ci, eslint, vitest). No Caddy/API compose checks.

Env (optional, for --test):
  OFDD_BOOTSTRAP_INSTALL_DEV=1   pip install -U pip setuptools wheel && pip install -e ".[dev]" before pytest
  OFDD_BOOTSTRAP_FRONTEND_TEST=1 npm ci + lint + vitest in afdd_stack/frontend (requires Node/npm)
  OFDD_PYTEST_ARGS               extra arguments passed to pytest (quoted string)

Env (optional, for ForwardHistorian template / logs):
  OFDD_FORWARD_CONFIG_OUT        absolute path for --write-forward-historian-config-template (required)
  OFDD_FORWARD_CENTRAL_VIP       destination-vip value (default tcp://127.0.0.1:22916)
  OFDD_VOLTTRON_DOCKER_SERVICE   docker compose service for exec (default volttron1)
  OFDD_VOLTTRON_AUTH_CREDENTIALS  public key / credential string for --volttron-docker-auth-add (sensitive — export in shell only)
  OFDD_VOLTTRON_REMOTE_USER_ID    identity string for --volttron-docker-auth-remote-approve
  OFDD_VOLTTRON_CONFIG_MAX_LINES  lines of config to print (default 120)
  OFDD_VOLTTRON_LOG_LINES         tail -n for --volttron-docker-tail-logs (default 200)
  OFDD_VOLTTRON_LOG_GREP          if set, pipe volttron.log through: grep -E "\$OFDD_VOLTTRON_LOG_GREP" | tail

Env (optional, for VOLTTRON_HOME / volttron-docker):
  OFDD_VOLTTRON_CONFIG_STRICT=1  do not auto-quarantine duplicate web-ssl-cert / web-ssl-key in \$VOLTTRON_HOME/config
  OFDD_VOLTTRON_LAB_SKIP_PUSH=1   with --volttron-docker-lab-up: do not copy lab templates first
  OFDD_VOLTTRON_LAB_NO_BACKUP=1   with --volttron-docker-lab-push: overwrite without timestamped backups
  OFDD_VOLTTRON_DOCKER_DOWN_VOLUMES=1  with --volttron-docker-lab-down: remove named volumes (compose down -v)
  LOCAL_USER_ID                 UID for volttron-docker gosu (default: current user from id -u when using lab-up)
  OFDD_COMPOSE_DB_MAX_WAIT      max seconds to wait for Postgres after --compose-db (default 90)

EOF
}

have_cmd() { command -v "$1" >/dev/null 2>&1; }

volttron_home() {
  echo "${VOLTTRON_HOME:-$HOME/.volttron}"
}

docker_compose_cmd() {
  if docker compose version >/dev/null 2>&1; then
    echo "docker compose"
    return 0
  fi
  if have_cmd docker-compose; then
    echo "docker-compose"
    return 0
  fi
  return 1
}

# docker compose up --wait has hung for some users after services already show Healthy (Compose/Docker edge cases).
# We start the container then poll pg_isready with a hard cap instead.
wait_openfdd_postgres_ready() {
  local max i ok
  max="${OFDD_COMPOSE_DB_MAX_WAIT:-90}"
  if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -qx 'openfdd_timescale'; then
    echo "[FAIL] Container openfdd_timescale not running after compose up. Try: cd \"$STACK_DIR\" && docker compose ps" >&2
    exit 1
  fi
  echo "=== Waiting for Postgres (openfdd), max ${max}s (pg_isready) ==="
  ok=0
  for i in $(seq 1 "$max"); do
    if docker exec openfdd_timescale pg_isready -U postgres -d openfdd >/dev/null 2>&1; then
      ok=1
      echo "[OK]   Postgres ready after ${i}s"
      break
    fi
    if (( i % 5 == 1 )); then
      echo "[INFO] $(date -Iseconds) waiting for pg_isready ($i/${max})…"
    fi
    sleep 1
  done
  if [[ "$ok" -ne 1 ]]; then
    echo "[FAIL] Postgres did not become ready in ${max}s. Check: docker logs openfdd_timescale" >&2
    exit 1
  fi
}

run_compose_db() {
  if ! have_cmd docker; then
    echo "[SKIP] docker not in PATH — install Docker to use --compose-db"
    return 0
  fi
  if ! docker_compose_cmd >/dev/null 2>&1; then
    echo "[SKIP] docker compose not available"
    return 0
  fi
  local dc
  dc="$(docker_compose_cmd)"
  echo "=== Starting Timescale (openfdd schema init from stack/sql) ==="
  echo "[INFO] $(date -Iseconds) compose: COMPOSE_HTTP_TIMEOUT=${COMPOSE_HTTP_TIMEOUT} DOCKER_CLIENT_TIMEOUT=${DOCKER_CLIENT_TIMEOUT}"
  (
    cd "$STACK_DIR"
    $dc up -d db
  )
  wait_openfdd_postgres_ready
  echo "[INFO] $(date -Iseconds) compose finished OK"
  echo "DB: postgresql://postgres:postgres@127.0.0.1:5432/openfdd"
}

run_doctor() {
  echo "=== Open-FDD bootstrap doctor (read-only) ==="
  echo ""
  local fail=0
  if have_cmd git; then
    echo "[OK]   git: $(git --version 2>/dev/null | head -1)"
  else
    echo "[FAIL] git not found (needed for --volttron-docker)"
    fail=1
  fi
  if have_cmd python3; then
    echo "[OK]   python3: $(python3 --version 2>/dev/null | head -1) (for host tools / --smoke-fdd-loop / monorepo)"
  else
    echo "[WARN] python3 not found (install for local Open-FDD tooling)"
  fi
  echo "[INFO] uname: $(uname -a 2>/dev/null || true)"
  echo "[INFO] OFDD_VOLTTRON_DOCKER_DIR=$VOLTTRON_DOCKER_DIR"
  echo "[INFO] default TZ / Open-Meteo: $DEFAULT_TZ ($DEFAULT_LAT, $DEFAULT_LON)"
  echo "[INFO] vcfg cert locality defaults: $CERT_COUNTRY / $CERT_STATE / $CERT_LOCALITY"
  echo "[INFO] open-fdd monorepo: $REPO_ROOT"
  echo "[INFO] afdd_stack: $AFDD_ROOT"
  if [[ -d "$REPO_ROOT/afdd_stack/openfdd_stack/volttron_bridge" ]]; then
    echo "[OK]   volttron_bridge package present"
  else
    echo "[WARN] volttron_bridge not found"
  fi
  if have_cmd docker; then
    echo "[OK]   docker: $(docker --version 2>/dev/null | head -1)"
  else
    echo "[FAIL] docker not in PATH (required for VOLTTRON in Docker and --compose-db)"
    fail=1
  fi
  if docker_compose_cmd >/dev/null 2>&1; then
    echo "[OK]   $(docker_compose_cmd) available"
  else
    echo "[FAIL] docker compose / docker-compose not found"
    fail=1
  fi
  if [[ -d "$VOLTTRON_DOCKER_DIR/.git" ]]; then
    echo "[OK]   volttron-docker checkout: $VOLTTRON_DOCKER_DIR"
  else
    echo "[INFO] No volttron-docker at $VOLTTRON_DOCKER_DIR (run --volttron-docker)"
  fi
  echo ""
  if [[ "$fail" -gt 0 ]]; then
    echo "Doctor: fix failures above."
    exit 1
  fi
  echo "Doctor: OK."
}

run_clone_volttron_docker() {
  have_cmd git || {
    echo "git required"
    exit 1
  }
  if [[ -d "$VOLTTRON_DOCKER_DIR/.git" ]]; then
    echo "=== Updating volttron-docker: $VOLTTRON_DOCKER_DIR ==="
    git -C "$VOLTTRON_DOCKER_DIR" fetch --all --prune || true
    git -C "$VOLTTRON_DOCKER_DIR" pull --ff-only || true
  else
    if [[ -e "$VOLTTRON_DOCKER_DIR" ]]; then
      echo "[FAIL] $VOLTTRON_DOCKER_DIR exists but is not a git checkout. Move or remove it, or set OFDD_VOLTTRON_DOCKER_DIR."
      exit 1
    fi
    echo "=== Cloning volttron-docker → $VOLTTRON_DOCKER_DIR ==="
    mkdir -p "$(dirname "$VOLTTRON_DOCKER_DIR")"
    git clone --depth 1 "$VOLTTRON_DOCKER_REPO" "$VOLTTRON_DOCKER_DIR" || {
      echo "[FAIL] git clone $VOLTTRON_DOCKER_REPO failed"
      exit 1
    }
  fi
  echo "Done. Official Docker workflow: $VOLTTRON_DOCKER_DIR/README.md"
  echo "  Build image (see README), then: cd \"$VOLTTRON_DOCKER_DIR\" && docker compose up"
  echo "  Mount a host dir as VOLTTRON_HOME (README \"Advanced Usage\") so VC state survives container restarts."
}

run_print_paths() {
  echo "export PYTHONPATH=\"${REPO_ROOT}:${AFDD_ROOT}:\${PYTHONPATH:-}\""
  echo "# Then: python3 -c 'from openfdd_stack.volttron_bridge import parse_device_subscription_topic'"
}

run_build_openfdd_ui() {
  have_cmd npm || {
    echo "npm required for --build-openfdd-ui"
    exit 1
  }
  echo "=== Building React (afdd_stack/frontend) ==="
  echo "[INFO] $(date -Iseconds) VITE_BASE_PATH=${VITE_BASE_PATH:-/openfdd/} (set for VOLTTRON Central static mount under /openfdd/)"
  (
    cd "$REPO_ROOT/afdd_stack/frontend"
    echo "[INFO] npm ci (set npm_config_loglevel=verbose for more npm output)"
    npm ci
    echo "[INFO] $(date -Iseconds) npm run build"
    VITE_BASE_PATH="${VITE_BASE_PATH:-/openfdd/}" npm run build
  )
  echo "[INFO] $(date -Iseconds) build finished"
  echo "Dist: $REPO_ROOT/afdd_stack/frontend/dist"
}

run_write_openfdd_ui_agent_config() {
  python3 - "$REPO_ROOT" <<'PY'
import json, pathlib, sys

root = pathlib.Path(sys.argv[1])
dist = root / "afdd_stack" / "frontend" / "dist"
cfg_path = root / "afdd_stack" / "volttron_agents" / "openfdd_central_ui" / "agent-config.json"
cfg_path.parent.mkdir(parents=True, exist_ok=True)
cfg_path.write_text(
    json.dumps({"web_root": str(dist.resolve())}, indent=2) + "\n",
    encoding="utf-8",
)
print(f"Wrote {cfg_path} (web_root -> {dist})")
PY
}

# volttron-docker setup-platform.py can append web-ssl-cert/key to an existing config; if the file
# already contained those keys (e.g. partial rerun), ConfigParser raises DuplicateOptionError.
run_volttron_quarantine_duplicate_ssl_config() {
  local cfg="$1"
  [[ -f "$cfg" ]] || return 0
  if [[ "${OFDD_VOLTTRON_CONFIG_STRICT:-0}" == 1 ]]; then
    return 0
  fi
  local cert key
  cert=$(grep -cE '^[[:space:]]*web-ssl-cert[[:space:]]*=' "$cfg" 2>/dev/null || true)
  key=$(grep -cE '^[[:space:]]*web-ssl-key[[:space:]]*=' "$cfg" 2>/dev/null || true)
  cert=${cert:-0}
  key=${key:-0}
  if [[ "$cert" -gt 1 ]] || [[ "$key" -gt 1 ]]; then
    local bak="${cfg}.bak.duplicate-ssl.$(date +%s)"
    echo "[WARN] $cfg has duplicate web-ssl lines (web-ssl-cert=$cert web-ssl-key=$key); volttron-ctl will not start."
    echo "[INFO] Quarantining to $bak — next step rewrites a stub if you run --volttron-config-stub / --central-lab."
    mv "$cfg" "$bak"
  fi
}

run_volttron_config_stub() {
  local home
  home="$(volttron_home)"
  mkdir -p "$home"
  run_volttron_quarantine_duplicate_ssl_config "$home/config"
  if [[ -f "$home/config" ]]; then
    echo "[SKIP] $home/config already exists (remove it first if you want a stub)"
    return 0
  fi
  local inst bind
  bind="${OFDD_VOLTTRON_BIND_WEB:-http://127.0.0.1:8443}"
  if [[ "$VOLTTRON_ROLE" == "edge" ]]; then
    inst="${OFDD_VOLTTRON_INSTANCE_NAME:-openfdd-edge}"
    cat >"$home/config" <<EOF
[volttron]
instance-name = $inst
message-bus = zmq
vip-address = tcp://127.0.0.1:22916
bind-web-address = $bind
volttron-central-address = $CENTRAL_WEB
EOF
  else
    inst="${OFDD_VOLTTRON_INSTANCE_NAME:-openfdd-central}"
    cat >"$home/config" <<EOF
[volttron]
instance-name = $inst
message-bus = zmq
vip-address = tcp://127.0.0.1:22916
bind-web-address = $bind
EOF
  fi
  echo "Wrote stub $home/config (instance-name=$inst bind-web-address=$bind role=$VOLTTRON_ROLE)"
  echo "Next: mount this directory as the container user's VOLTTRON_HOME (see volttron-docker README)."
  echo "      ./scripts/bootstrap.sh --write-env-defaults"
  echo "      In the container: vcfg / vctl as documented upstream."
}

run_write_env_defaults() {
  local home logdir
  home="$(volttron_home)"
  logdir="${OFDD_VOLTTRON_LOG_DIR:-$home/logs}"
  mkdir -p "$home" "$logdir"
  local target="$home/openfdd-defaults.env"
  cat >"$target" <<EOF
# Open-FDD defaults for VOLTTRON Central + SQL FDD (generated by bootstrap.sh).
# Source before vcfg or agents:  set -a && source "$target" && set +a
#
TZ=$DEFAULT_TZ
OFDD_DB_DSN=$DB_DSN
OFDD_OPEN_METEO_LATITUDE=$DEFAULT_LAT
OFDD_OPEN_METEO_LONGITUDE=$DEFAULT_LON
OFDD_OPEN_METEO_TIMEZONE=$DEFAULT_TZ
# Host-side Open-FDD imports (agents / scripts); VOLTTRON itself runs inside the container image.
PYTHONPATH=$REPO_ROOT:$AFDD_ROOT:\${PYTHONPATH:-}
# Platform loop / rules (override if your tree layout differs)
# OFDD_RULES_DIR=$REPO_ROOT/afdd_stack/stack/rules
# OFDD_BRICK_TTL_PATH=$REPO_ROOT/afdd_stack/config/data_model.ttl
#
# When vcfg asks for HTTPS / CA certificate details, defaults match Chicago, IL:
#   Country:  $CERT_COUNTRY
#   State:    $CERT_STATE
#   Location: $CERT_LOCALITY
EOF
  echo "Wrote $target"
}

run_write_logrotate() {
  local home
  home="$(volttron_home)"
  local logdir="${OFDD_VOLTTRON_LOG_DIR:-$home/logs}"
  mkdir -p "$logdir"
  local frag="$home/logrotate-openfdd-volttron.conf"
  cat >"$frag" <<EOF
# Install on the host (paths are literal; edit if VOLTTRON_HOME differs):
#   sudo cp $frag /etc/logrotate.d/openfdd-volttron
# Or run ad-hoc:
#   logrotate -s $home/logrotate.state $frag
#
$logdir/volttron.log {
    daily
    rotate 14
    missingok
    notifempty
    copytruncate
    compress
    delaycompress
}
EOF
  echo "Wrote $frag"
  echo "[INFO] Logs are usually under the mounted VOLTTRON_HOME in the container; this fragment helps if you tee logs to the host."
}

_psql_openfdd() {
  local sql="$1"
  if have_cmd psql; then
    PGPASSWORD="${OFDD_PG_PASSWORD:-postgres}" psql -h "$PG_HOST" -U "${OFDD_PG_USER:-postgres}" -d openfdd -v ON_ERROR_STOP=1 -c "$sql"
    return $?
  fi
  if have_cmd docker && docker ps --format '{{.Names}}' 2>/dev/null | grep -qx 'openfdd_timescale'; then
    docker exec -i openfdd_timescale psql -U postgres -d openfdd -v ON_ERROR_STOP=1 -c "$sql"
    return $?
  fi
  echo "[FAIL] Need psql on PATH or running container openfdd_timescale (try --compose-db)."
  return 1
}

run_verify_fdd_schema() {
  echo "=== Verifying Open-FDD FDD / CRUD tables (fault rules + results) ==="
  local q
  q="
DO \$\$
DECLARE
  need text[] := ARRAY[
    'fault_definitions','fault_results','fdd_run_log','fault_state',
    'sites','equipment','points','timeseries_readings'
  ];
  miss text[] := ARRAY[]::text[];
  t text;
BEGIN
  FOREACH t IN ARRAY need LOOP
    IF to_regclass('public.' || t) IS NULL THEN
      miss := array_append(miss, t);
    END IF;
  END LOOP;
  IF cardinality(miss) > 0 THEN
    RAISE EXCEPTION 'missing tables: %', miss;
  END IF;
END \$\$;
SELECT 'schema_ok' AS status;
"
  if _psql_openfdd "$q"; then
    echo "[OK]   FDD schema tables present."
  else
    exit 1
  fi
}

run_smoke_fdd_loop() {
  echo "=== Smoke: openfdd_stack.platform.loop.run_fdd_loop() ==="
  export PYTHONPATH="${REPO_ROOT}:${AFDD_ROOT}:${PYTHONPATH:-}"
  export OFDD_DB_DSN="$DB_DSN"
  local py="python3"
  if ! "$py" -c "from openfdd_stack.platform.loop import run_fdd_loop; run_fdd_loop(); print('run_fdd_loop: OK')"; then
    echo "[FAIL] Smoke FDD loop failed (pip install -e \".[stack]\" in a venv, or set PYTHONPATH from --print-paths; ensure DB is up)."
    exit 1
  fi
  echo "[OK]   FDD loop completed (check fdd_run_log and logs for errors)."
}

run_bootstrap_test() {
  echo "=== Open-FDD bootstrap --test ==="
  (
    cd "$REPO_ROOT"
    if [[ "${OFDD_BOOTSTRAP_INSTALL_DEV:-0}" == "1" ]]; then
      echo "[INFO] OFDD_BOOTSTRAP_INSTALL_DEV=1 → pip install -e \".[dev]\" …"
      python3 -m pip install -U pip setuptools wheel
      python3 -m pip install -e ".[dev]"
    fi
    if ! python3 -c "import pytest" 2>/dev/null; then
      echo "[FAIL] pytest not available. Use a venv with dev deps, or: OFDD_BOOTSTRAP_INSTALL_DEV=1 $0 --test"
      exit 1
    fi
    echo "[INFO] $(date -Iseconds) pytest open_fdd/tests afdd_stack/openfdd_stack/tests${OFDD_PYTEST_ARGS:+ $OFDD_PYTEST_ARGS}"
    # shellcheck disable=SC2086
    python3 -m pytest open_fdd/tests afdd_stack/openfdd_stack/tests --tb=short ${OFDD_PYTEST_ARGS-}
  ) || exit 1
  if [[ "${OFDD_BOOTSTRAP_FRONTEND_TEST:-0}" == "1" ]]; then
    if ! have_cmd npm; then
      echo "[FAIL] OFDD_BOOTSTRAP_FRONTEND_TEST=1 but npm not in PATH"
      exit 1
    fi
    echo "=== Frontend: npm ci, lint, build (tsc), vitest ==="
    (
      cd "$REPO_ROOT/afdd_stack/frontend"
      npm ci
      npm run lint
      npm run build
      npm run test
    ) || exit 1
  elif have_cmd npm; then
    echo "[INFO] Skipping frontend tests (set OFDD_BOOTSTRAP_FRONTEND_TEST=1 to run eslint + vitest)."
  fi
  echo "[OK]   --test completed."
}

run_print_vcfg_hints() {
  local vh
  vh="$(volttron_home)"
  cat <<EOF
=== VOLTTRON in Docker (volttron-docker) + Central ===

Repo on disk: $VOLTTRON_DOCKER_DIR  (update with: $0 --volttron-docker)
Upstream README: $VOLTTRON_DOCKER_DIR/README.md  — build the image, \`docker compose up\`, set \`platform_config.yml\`, mount \$VOLTTRON_HOME.

Chicago, IL defaults when prompted for certificate / locality:
  Country:  $CERT_COUNTRY
  State:    $CERT_STATE
  Location: $CERT_LOCALITY

Host env (optional): $vh/openfdd-defaults.env — TZ, OFDD_*, PYTHONPATH for Open-FDD (see --write-env-defaults).

Typical steps (inside the running container or per volttron-docker docs):
1) Web-enabled instance (bind-web-address), Volttron Central, historians, drivers — \`vcfg\` / \`vctl\` as upstream.
2) Edge: set OFDD_VOLTTRON_ROLE=edge and re-run --volttron-config-stub on the host (stub lands under the mounted VOLTTRON_HOME).

Open-FDD UI (host build, then install agent in container):
  ./scripts/bootstrap.sh --build-openfdd-ui
  ./scripts/bootstrap.sh --write-openfdd-ui-agent-config
  See afdd_stack/volttron_agents/openfdd_central_ui/README.md

Logs: $vh/logrotate-openfdd-volttron.conf (if you rotate host-visible volttron.log)

Official walkthrough:
  https://volttron.readthedocs.io/en/main/deploying-volttron/multi-platform/volttron-central-deployment.html

Open-FDD UI is served at /openfdd/ (build with VITE_BASE_PATH=/openfdd/). Central UI stays at /vc/ (upstream default).

FDD on DB: fault_definitions sync from YAML rules; fault_results + fdd_run_log written by run_fdd_loop (agent or --smoke-fdd-loop on the host).
EOF
}

run_central_lab() {
  echo "=== Open-FDD central-lab bundle ==="
  run_compose_db
  run_volttron_config_stub
  run_write_env_defaults
  run_write_logrotate
  run_verify_fdd_schema
  run_clone_volttron_docker
  echo ""
  echo "=== Next: start VOLTTRON in Docker (upstream checkout; do not commit Open-F-DD files there) ==="
  echo "  LOCAL_USER_ID=\$(id -u) \"$REPO_ROOT/scripts/bootstrap.sh\" --volttron-docker-lab-up"
  echo "  # Or manually: \"$REPO_ROOT/scripts/volttron-docker.sh\" up -d"
  echo "  # Build the image first if needed: see $VOLTTRON_DOCKER_DIR/README.md"
  echo "  # Mount $(volttron_home) as VOLTTRON_HOME in the container if you used the stubs above."
  echo "  \"$REPO_ROOT/scripts/bootstrap.sh\" --print-vcfg-hints"
}



run_print_forward_historian_cheatsheet() {
  local doc="$REPO_ROOT/docs/howto/edge_forward_historian_to_central.md"
  echo "=== Edge ForwardHistorian → Central (cheat sheet) ==="
  if [[ -f "$doc" ]]; then
    echo "Full doc: file://$doc"
    echo "Published path: docs/howto/edge_forward_historian_to_central.md"
  else
    echo "[WARN] Missing $doc (use a full Open-F-DD clone)."
  fi
  cat <<'CHEAT'

--- Central (Docker host): manual docker vs ./scripts/bootstrap.sh (repo root) ---
  docker exec -itu volttron volttron1 bash     →  ./scripts/bootstrap.sh --volttron-docker-bash
  vctl auth serverkey                           →  ./scripts/bootstrap.sh --volttron-docker-serverkey
  cat \$VOLTTRON_HOME/config                    →  ./scripts/bootstrap.sh --volttron-docker-cat-config
  vctl auth add --credentials <Pi_pubkey>       →  OFDD_VOLTTRON_AUTH_CREDENTIALS='<Pi_pubkey>' ./scripts/bootstrap.sh --volttron-docker-auth-add
  vctl auth remote list / approve               →  ./scripts/bootstrap.sh --volttron-docker-auth-remote-list
                                                →  OFDD_VOLTTRON_REMOTE_USER_ID='<id>' ./scripts/bootstrap.sh --volttron-docker-auth-remote-approve
  vctl list / vctl status                       →  ./scripts/bootstrap.sh --volttron-docker-agents / --volttron-docker-agent-status
  tail volttron.log                             →  ./scripts/bootstrap.sh --volttron-docker-tail-logs

Order (high level):
  1) Central: server key (bootstrap flags above, or vctl inside --volttron-docker-bash).
  2) Edge (Pi / native VOLTTRON): write forward JSON → vctl install/start ForwardHistorian → vctl auth publickey --tag forward-to-central
  3) Central: vctl auth add --credentials <publickey from step 2> (use --volttron-docker-auth-add on host).
  4) Edge: vctl stop/start --tag forward-to-central

Central logs (from Open-F-DD host; no docker exec typing):
  ./scripts/bootstrap.sh --volttron-docker-tail-logs
  OFDD_VOLTTRON_LOG_GREP='forward|vip|auth|error' ./scripts/bootstrap.sh --volttron-docker-tail-logs

Edge logs (on edge host only):
  tail -n 120 "\$VOLTTRON_HOME/volttron.log"

CHEAT
}

run_write_forward_historian_config_template() {
  local out="${OFDD_FORWARD_CONFIG_OUT:-}"
  if [[ -z "$out" ]]; then
    echo "[FAIL] Set OFDD_FORWARD_CONFIG_OUT=/absolute/path/forward-to-central.json" >&2
    exit 1
  fi
  local vip="${OFDD_FORWARD_CENTRAL_VIP:-tcp://127.0.0.1:22916}"
  mkdir -p "$(dirname "$out")"
  cat >"$out" <<EOF
{
  "destination-vip": "${vip}",
  "destination-serverkey": "REPLACE_WITH_OUTPUT_OF_vctl_auth_serverkey_ON_CENTRAL",
  "capture_log_data": false
}
EOF
  echo "[OK]   Wrote ForwardHistorian template: $out"
  echo "       Replace destination-serverkey after: \"$REPO_ROOT/scripts/bootstrap.sh\" --volttron-docker-serverkey"
  chmod 600 "$out" 2>/dev/null || true
}

run_print_volttron_central_sql_forward_poc() {
  cat <<'POC'
=== Open-F-DD: Central for SQL + ForwardHistorian (lab mental model) ===

Goal
  - Central (Docker): SQL historian / aggregation; optional Central UI. Skip BACnet proxy / platform driver on Central unless you need them.
  - Edges: BACnet + drivers locally; ForwardHistorian to Central VIP (usually tcp://CENTRAL_IP:22916).

Open-F-DD scope
  - This repo does not modify ~/volttron-docker. Curate agents with upstream platform_config.yml and vctl inside the container.
  - Host --central-lab stubs apply to the live container only if that VOLTTRON_HOME is bind-mounted (see docs/howto/volttron_central_and_parity.md).

Commands
  ./scripts/bootstrap.sh --print-forward-historian-cheatsheet
  OFDD_FORWARD_CENTRAL_VIP='tcp://CENTRAL_LAN_IP:22916' OFDD_FORWARD_CONFIG_OUT=/tmp/forward-to-central.json \
    ./scripts/bootstrap.sh --write-forward-historian-config-template

  # Central Docker from host — wrappers call vctl / cat inside the container:
  ./scripts/bootstrap.sh --volttron-docker-serverkey
  ./scripts/bootstrap.sh --volttron-docker-cat-config
  ./scripts/bootstrap.sh --volttron-docker-show-config
  ./scripts/bootstrap.sh --volttron-docker-auth-remote-list
  OFDD_VOLTTRON_AUTH_CREDENTIALS='<edge-forwarder-pubkey>' ./scripts/bootstrap.sh --volttron-docker-auth-add
  OFDD_VOLTTRON_REMOTE_USER_ID='<pending-id>' ./scripts/bootstrap.sh --volttron-docker-auth-remote-approve
  OFDD_VOLTTRON_LOG_GREP='forward|vip|auth|error' ./scripts/bootstrap.sh --volttron-docker-tail-logs

POC
  run_print_forward_historian_cheatsheet
}

volttron_docker_service() {
  echo "${OFDD_VOLTTRON_DOCKER_SERVICE:-volttron1}"
}

require_docker_volttron_container() {
  local c
  c="$(volttron_docker_service)"
  if ! have_cmd docker; then
    echo "[FAIL] docker not in PATH" >&2
    exit 1
  fi
  if ! docker info >/dev/null 2>&1; then
    echo "[FAIL] Docker daemon not reachable" >&2
    exit 1
  fi
  if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$c"; then
    echo "[FAIL] container '$c' is not running. Try: \"$REPO_ROOT/scripts/volttron-docker.sh\" ps && up -d" >&2
    exit 1
  fi
}

run_volttron_docker_serverkey() {
  require_docker_volttron_container
  local c
  c="$(volttron_docker_service)"
  echo "[INFO] $(date -Iseconds) Central platform server key (vctl auth serverkey in container $c)"
  echo "[INFO] Manual equivalent: docker exec -itu volttron $c bash -lc 'vctl auth serverkey'"
  # Non-interactive exec has no login PATH; vctl lives under ~/.local/bin in upstream images.
  echo "Central server key:"
  docker exec --user volttron "$c" sh -lc 'vctl auth serverkey'
}

run_volttron_docker_bash() {
  require_docker_volttron_container
  local c
  c="$(volttron_docker_service)"
  echo "[INFO] Interactive shell in $c as user volttron (upstream: docker exec -itu volttron $c bash). Exit bash to return." >&2
  exec docker exec -itu volttron "$c" bash
}

run_volttron_docker_show_config() {
  require_docker_volttron_container
  local n="${OFDD_VOLTTRON_CONFIG_MAX_LINES:-120}"
  echo "[INFO] $(date -Iseconds) sed 1,$n \$VOLTTRON_HOME/config (container $(volttron_docker_service))"
  docker exec --user volttron "$(volttron_docker_service)" sh -lc 'sed -n "1,'"$n"'p" "$VOLTTRON_HOME/config"'
}

run_volttron_docker_cat_config() {
  require_docker_volttron_container
  echo "[INFO] $(date -Iseconds) cat \$VOLTTRON_HOME/config (container $(volttron_docker_service))"
  docker exec --user volttron "$(volttron_docker_service)" sh -lc 'cat "$VOLTTRON_HOME/config"'
}

run_volttron_docker_auth_remote_list() {
  require_docker_volttron_container
  docker exec --user volttron "$(volttron_docker_service)" sh -lc 'vctl auth remote list'
}

run_volttron_docker_auth_remote_approve() {
  require_docker_volttron_container
  if [[ -z "${OFDD_VOLTTRON_REMOTE_USER_ID:-}" ]]; then
    echo "[FAIL] Set OFDD_VOLTTRON_REMOTE_USER_ID (from vctl auth remote list on Central)." >&2
    exit 1
  fi
  echo "[INFO] $(date -Iseconds) vctl auth remote approve \"$OFDD_VOLTTRON_REMOTE_USER_ID\""
  docker exec -e OFDD_VOLTTRON_REMOTE_USER_ID="$OFDD_VOLTTRON_REMOTE_USER_ID" --user volttron "$(volttron_docker_service)" \
    sh -lc 'vctl auth remote approve "$OFDD_VOLTTRON_REMOTE_USER_ID"'
}

run_volttron_docker_auth_add() {
  require_docker_volttron_container
  if [[ -z "${OFDD_VOLTTRON_AUTH_CREDENTIALS:-}" ]]; then
    echo "[FAIL] Set OFDD_VOLTTRON_AUTH_CREDENTIALS (edge forwarder public key from: vctl auth publickey --tag forward-to-central)." >&2
    exit 1
  fi
  echo "[INFO] $(date -Iseconds) vctl auth add --credentials … (${#OFDD_VOLTTRON_AUTH_CREDENTIALS} chars)"
  docker exec -e OFDD_VOLTTRON_AUTH_CREDENTIALS="$OFDD_VOLTTRON_AUTH_CREDENTIALS" --user volttron "$(volttron_docker_service)" \
    sh -lc 'vctl auth add --credentials "$OFDD_VOLTTRON_AUTH_CREDENTIALS"'
}

run_volttron_docker_tail_logs() {
  require_docker_volttron_container
  local c n
  c="$(volttron_docker_service)"
  n="${OFDD_VOLTTRON_LOG_LINES:-200}"
  if [[ -n "${OFDD_VOLTTRON_LOG_GREP:-}" ]]; then
    docker exec -e G="${OFDD_VOLTTRON_LOG_GREP}" -e N="$n" --user volttron "$c" \
      sh -lc 'grep -E "$G" "$VOLTTRON_HOME/volttron.log" | tail -n "$N"'
  else
    docker exec -e N="$n" --user volttron "$c" sh -lc 'tail -n "$N" "$VOLTTRON_HOME/volttron.log"'
  fi
}

volttron_docker_lab_dir() {
  echo "$SCRIPT_DIR/volttron_docker_lab"
}

require_volttron_docker_checkout() {
  if [[ ! -d "$VOLTTRON_DOCKER_DIR" ]]; then
    echo "[FAIL] Missing volttron-docker directory: $VOLTTRON_DOCKER_DIR" >&2
    echo "       Run: \"$REPO_ROOT/scripts/bootstrap.sh\" --volttron-docker" >&2
    exit 1
  fi
  if [[ ! -f "$VOLTTRON_DOCKER_DIR/docker-compose.yml" ]]; then
    echo "[FAIL] No docker-compose.yml in $VOLTTRON_DOCKER_DIR" >&2
    exit 1
  fi
}

volttron_docker_run_compose() {
  require_volttron_docker_checkout
  local dc
  dc="$(docker_compose_cmd)" || {
    echo "[FAIL] docker compose not available" >&2
    exit 1
  }
  (
    cd "$VOLTTRON_DOCKER_DIR"
    if [[ -f docker-compose.openfdd.override.yml ]]; then
      # shellcheck disable=SC2086
      $dc -f docker-compose.yml -f docker-compose.openfdd.override.yml "$@"
    else
      # shellcheck disable=SC2086
      $dc -f docker-compose.yml "$@"
    fi
  )
}

run_volttron_docker_lab_push() {
  local lab
  lab="$(volttron_docker_lab_dir)"
  require_volttron_docker_checkout
  if [[ ! -d "$lab" ]]; then
    echo "[FAIL] Missing lab template directory: $lab" >&2
    exit 1
  fi
  for need in platform_config.yml historian.config docker-compose.openfdd.override.yml; do
    if [[ ! -f "$lab/$need" ]]; then
      echo "[FAIL] Missing lab template file: $lab/$need" >&2
      exit 1
    fi
  done
  mkdir -p "$VOLTTRON_DOCKER_DIR/configs"
  _lab_backup() {
    local f="$1"
    [[ -f "$f" ]] || return 0
    [[ "${OFDD_VOLTTRON_LAB_NO_BACKUP:-0}" == 1 ]] && return 0
    cp -a "$f" "${f}.bak.$(date +%s)"
    echo "[INFO] Backed up $f"
  }
  echo "=== Lab push → $VOLTTRON_DOCKER_DIR ==="
  _lab_backup "$VOLTTRON_DOCKER_DIR/platform_config.yml"
  cp -a "$lab/platform_config.yml" "$VOLTTRON_DOCKER_DIR/platform_config.yml"
  _lab_backup "$VOLTTRON_DOCKER_DIR/configs/historian.config"
  cp -a "$lab/historian.config" "$VOLTTRON_DOCKER_DIR/configs/historian.config"
  _lab_backup "$VOLTTRON_DOCKER_DIR/docker-compose.openfdd.override.yml"
  cp -a "$lab/docker-compose.openfdd.override.yml" "$VOLTTRON_DOCKER_DIR/docker-compose.openfdd.override.yml"
  echo "[OK]   Lab templates installed (Central + SQLHistorian → db:5432/openfdd on network stack_default)."
  echo "       Start DB first: \"$REPO_ROOT/scripts/bootstrap.sh\" --compose-db"
  echo "       Then:            LOCAL_USER_ID=\$(id -u) \"$REPO_ROOT/scripts/bootstrap.sh\" --volttron-docker-lab-up"
}

run_volttron_docker_install_pg_driver() {
  require_docker_volttron_container
  local c
  c="$(volttron_docker_service)"
  echo "[INFO] $(date -Iseconds) Installing psycopg2-binary in container $c (root pip; stock image often lacks Postgres driver)"
  docker exec -u root "$c" sh -lc \
    'python3 -m pip install -U pip setuptools wheel >/dev/null 2>&1 || true; python3 -m pip install --only-binary=:all: "psycopg2-binary"' \
    || {
      echo "[WARN] pip install psycopg2-binary failed; SQLHistorian→Postgres may still fail until driver is available." >&2
      return 0
    }
  docker exec -u root "$c" python3 -c "import psycopg2" 2>/dev/null && echo "[OK]   psycopg2 import works in container."
}

run_volttron_docker_lab_down() {
  require_volttron_docker_checkout
  local vol=()
  [[ "${OFDD_VOLTTRON_DOCKER_DOWN_VOLUMES:-0}" == 1 ]] && vol=(-v)
  if [[ "${#vol[@]}" -gt 0 ]]; then
    echo "=== docker compose down -v in $VOLTTRON_DOCKER_DIR ==="
  else
    echo "=== docker compose down in $VOLTTRON_DOCKER_DIR ==="
  fi
  volttron_docker_run_compose down "${vol[@]}"
}

run_volttron_docker_lab_up() {
  have_cmd docker || {
    echo "[FAIL] docker not in PATH" >&2
    exit 1
  }
  export LOCAL_USER_ID="${LOCAL_USER_ID:-$(id -u)}"
  echo "[INFO] LOCAL_USER_ID=$LOCAL_USER_ID (volttron-docker gosu)"
  if [[ "${OFDD_VOLTTRON_LAB_SKIP_PUSH:-0}" != 1 ]]; then
    run_volttron_docker_lab_push
  else
    require_volttron_docker_checkout
    echo "[INFO] OFDD_VOLTTRON_LAB_SKIP_PUSH=1 — not copying lab templates"
  fi
  if [[ -f "$VOLTTRON_DOCKER_DIR/docker-compose.openfdd.override.yml" ]] && ! docker network inspect stack_default >/dev/null 2>&1; then
    echo "[FAIL] Docker network stack_default not found. Start the DB stack first so it is created, e.g.:" >&2
    echo "       \"$REPO_ROOT/scripts/bootstrap.sh\" --compose-db" >&2
    exit 1
  fi
  echo "=== docker compose up -d in $VOLTTRON_DOCKER_DIR ==="
  volttron_docker_run_compose up -d
  local c i
  c="$(volttron_docker_service)"
  echo "[INFO] Waiting for container $c …"
  for i in $(seq 1 90); do
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$c"; then
      echo "[OK]   $c is running (${i}s)"
      break
    fi
    if [[ "$i" -eq 90 ]]; then
      echo "[FAIL] $c did not start in time. Try: \"$REPO_ROOT/scripts/bootstrap.sh\" --volttron-docker-compose -- ps" >&2
      exit 1
    fi
    sleep 1
  done
  # Wait until docker exec works, then install Postgres driver for SQLHistorian
  sleep 3
  for i in $(seq 1 30); do
    if docker exec -u root "$c" true 2>/dev/null; then
      break
    fi
    sleep 2
  done
  run_volttron_docker_install_pg_driver || true
  echo ""
  echo "=== Next (no shell inside container required) ==="
  echo "  https://127.0.0.1:8443/index.html        # first-time admin (self-signed cert)"
  echo "  https://127.0.0.1:8443/vc/index.html     # Volttron Central UI"
  echo "  \"$REPO_ROOT/scripts/bootstrap.sh\" --volttron-docker-serverkey   # same as vctl auth serverkey in container"
  echo "  \"$REPO_ROOT/scripts/bootstrap.sh\" --volttron-docker-cat-config   # same as cat \$VOLTTRON_HOME/config"
  echo "  \"$REPO_ROOT/scripts/bootstrap.sh\" --volttron-docker-bash       # optional: interactive bash as volttron"
  echo "  \"$REPO_ROOT/scripts/bootstrap.sh\" --volttron-docker-agents"
  echo "  \"$REPO_ROOT/scripts/bootstrap.sh\" --volttron-docker-tail-logs"
}

run_volttron_docker_compose() {
  if [[ "${#VOLTTRON_DOCKER_COMPOSE_ARGS[@]}" -eq 0 ]]; then
    VOLTTRON_DOCKER_COMPOSE_ARGS=(ps)
    echo "[INFO] No args after --volttron-docker-compose; defaulting to: ps"
  fi
  echo "=== docker compose ${VOLTTRON_DOCKER_COMPOSE_ARGS[*]} (in $VOLTTRON_DOCKER_DIR) ==="
  volttron_docker_run_compose "${VOLTTRON_DOCKER_COMPOSE_ARGS[@]}"
}

run_volttron_docker_agents() {
  require_docker_volttron_container
  docker exec --user volttron "$(volttron_docker_service)" sh -lc 'vctl list'
}

run_volttron_docker_agent_status() {
  require_docker_volttron_container
  docker exec --user volttron "$(volttron_docker_service)" sh -lc 'vctl status'
}


any_true() {
  $DOCTOR || $VOLTTRON_DOCKER || $PRINT_PATHS || $COMPOSE_DB \
    || $BUILD_OPENFDD_UI || $WRITE_OPENFDD_UI_AGENT_CONFIG || $VOLTTRON_CONFIG_STUB \
    || $PRINT_VCFG_HINTS || $WRITE_ENV_DEFAULTS || $WRITE_LOGROTATE \
    || $VERIFY_FDD_SCHEMA || $SMOKE_FDD_LOOP || $CENTRAL_LAB || $TEST \
    || $PRINT_FORWARD_HISTORIAN_CHEATSHEET || $WRITE_FORWARD_HISTORIAN_CONFIG_TEMPLATE \
    || $PRINT_VOLTTRON_CENTRAL_SQL_FORWARD_POC \
    || $VOLTTRON_DOCKER_SERVERKEY || $VOLTTRON_DOCKER_SHOW_CONFIG || $VOLTTRON_DOCKER_CAT_CONFIG || $VOLTTRON_DOCKER_AUTH_REMOTE_LIST \
    || $VOLTTRON_DOCKER_AUTH_REMOTE_APPROVE || $VOLTTRON_DOCKER_AUTH_ADD || $VOLTTRON_DOCKER_TAIL_LOGS \
    || $VOLTTRON_DOCKER_LAB_PUSH || $VOLTTRON_DOCKER_LAB_UP || $VOLTTRON_DOCKER_LAB_DOWN \
    || $VOLTTRON_DOCKER_INSTALL_PG_DRIVER || $VOLTTRON_DOCKER_AGENTS || $VOLTTRON_DOCKER_AGENT_STATUS \
    || $VOLTTRON_DOCKER_BASH || $VOLTTRON_DOCKER_COMPOSE
}

if [[ $# -eq 0 ]]; then
  usage
  exit 0
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h | --help) usage; exit 0 ;;
    --doctor) DOCTOR=true ;;
    --volttron-docker) VOLTTRON_DOCKER=true ;;
    --clone-volttron-docker) VOLTTRON_DOCKER=true ;;
    --print-paths) PRINT_PATHS=true ;;
    --compose-db) COMPOSE_DB=true ;;
    --build-openfdd-ui) BUILD_OPENFDD_UI=true ;;
    --write-openfdd-ui-agent-config) WRITE_OPENFDD_UI_AGENT_CONFIG=true ;;
    --volttron-config-stub) VOLTTRON_CONFIG_STUB=true ;;
    --print-vcfg-hints) PRINT_VCFG_HINTS=true ;;
    --write-env-defaults) WRITE_ENV_DEFAULTS=true ;;
    --write-logrotate) WRITE_LOGROTATE=true ;;
    --verify-fdd-schema) VERIFY_FDD_SCHEMA=true ;;
    --smoke-fdd-loop) SMOKE_FDD_LOOP=true ;;
    --central-lab) CENTRAL_LAB=true ;;
    --print-forward-historian-cheatsheet) PRINT_FORWARD_HISTORIAN_CHEATSHEET=true ;;
    --write-forward-historian-config-template) WRITE_FORWARD_HISTORIAN_CONFIG_TEMPLATE=true ;;
    --print-volttron-central-sql-forward-poc) PRINT_VOLTTRON_CENTRAL_SQL_FORWARD_POC=true ;;
    --volttron-docker-serverkey) VOLTTRON_DOCKER_SERVERKEY=true ;;
    --volttron-docker-show-config) VOLTTRON_DOCKER_SHOW_CONFIG=true ;;
    --volttron-docker-cat-config) VOLTTRON_DOCKER_CAT_CONFIG=true ;;
    --volttron-docker-auth-remote-list) VOLTTRON_DOCKER_AUTH_REMOTE_LIST=true ;;
    --volttron-docker-auth-remote-approve) VOLTTRON_DOCKER_AUTH_REMOTE_APPROVE=true ;;
    --volttron-docker-auth-add) VOLTTRON_DOCKER_AUTH_ADD=true ;;
    --volttron-docker-tail-logs) VOLTTRON_DOCKER_TAIL_LOGS=true ;;
    --volttron-docker-lab-push) VOLTTRON_DOCKER_LAB_PUSH=true ;;
    --volttron-docker-lab-up) VOLTTRON_DOCKER_LAB_UP=true ;;
    --volttron-docker-lab-down) VOLTTRON_DOCKER_LAB_DOWN=true ;;
    --volttron-docker-install-pg-driver) VOLTTRON_DOCKER_INSTALL_PG_DRIVER=true ;;
    --volttron-docker-agents) VOLTTRON_DOCKER_AGENTS=true ;;
    --volttron-docker-agent-status) VOLTTRON_DOCKER_AGENT_STATUS=true ;;
    --volttron-docker-bash) VOLTTRON_DOCKER_BASH=true ;;
    --volttron-docker-compose)
      shift
      VOLTTRON_DOCKER_COMPOSE_ARGS=("$@")
      VOLTTRON_DOCKER_COMPOSE=true
      break
      ;;
    --test) TEST=true ;;
    *)
      echo "Unknown option: $1"
      usage
      exit 1
      ;;
  esac
  shift
done

$DOCTOR && run_doctor
$VOLTTRON_DOCKER && run_clone_volttron_docker
$PRINT_PATHS && run_print_paths
$COMPOSE_DB && run_compose_db
$BUILD_OPENFDD_UI && run_build_openfdd_ui
$WRITE_OPENFDD_UI_AGENT_CONFIG && run_write_openfdd_ui_agent_config
$VOLTTRON_CONFIG_STUB && run_volttron_config_stub
$WRITE_ENV_DEFAULTS && run_write_env_defaults
$WRITE_LOGROTATE && run_write_logrotate
$VERIFY_FDD_SCHEMA && run_verify_fdd_schema
$SMOKE_FDD_LOOP && run_smoke_fdd_loop
$PRINT_VCFG_HINTS && run_print_vcfg_hints
$CENTRAL_LAB && run_central_lab
$PRINT_FORWARD_HISTORIAN_CHEATSHEET && run_print_forward_historian_cheatsheet
$WRITE_FORWARD_HISTORIAN_CONFIG_TEMPLATE && run_write_forward_historian_config_template
$PRINT_VOLTTRON_CENTRAL_SQL_FORWARD_POC && run_print_volttron_central_sql_forward_poc
$VOLTTRON_DOCKER_SERVERKEY && run_volttron_docker_serverkey
$VOLTTRON_DOCKER_SHOW_CONFIG && run_volttron_docker_show_config
$VOLTTRON_DOCKER_CAT_CONFIG && run_volttron_docker_cat_config
$VOLTTRON_DOCKER_AUTH_REMOTE_LIST && run_volttron_docker_auth_remote_list
$VOLTTRON_DOCKER_AUTH_REMOTE_APPROVE && run_volttron_docker_auth_remote_approve
$VOLTTRON_DOCKER_AUTH_ADD && run_volttron_docker_auth_add
$VOLTTRON_DOCKER_TAIL_LOGS && run_volttron_docker_tail_logs
$VOLTTRON_DOCKER_LAB_PUSH && run_volttron_docker_lab_push
$VOLTTRON_DOCKER_LAB_DOWN && run_volttron_docker_lab_down
$VOLTTRON_DOCKER_COMPOSE && run_volttron_docker_compose
$VOLTTRON_DOCKER_LAB_UP && run_volttron_docker_lab_up
$VOLTTRON_DOCKER_INSTALL_PG_DRIVER && run_volttron_docker_install_pg_driver
$VOLTTRON_DOCKER_AGENTS && run_volttron_docker_agents
$VOLTTRON_DOCKER_AGENT_STATUS && run_volttron_docker_agent_status
$TEST && run_bootstrap_test
$VOLTTRON_DOCKER_BASH && run_volttron_docker_bash

if ! any_true; then
  usage
fi
