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
#
# Quick start (from open-fdd repo root):
#   ./afdd_stack/scripts/bootstrap.sh --central-lab
#   # Then build the image and start VOLTTRON (see $HOME/volttron-docker/README.md):
#   cd "$HOME/volttron-docker" && docker compose up
#
# Optional UI + Central prep (still from repo root):
#   ./afdd_stack/scripts/bootstrap.sh --build-openfdd-ui
#   ./afdd_stack/scripts/bootstrap.sh --write-openfdd-ui-agent-config
#   ./afdd_stack/scripts/bootstrap.sh --volttron-config-stub
#   ./afdd_stack/scripts/bootstrap.sh --print-vcfg-hints
#
# Local verification (no Docker services required for pytest):
#   ./afdd_stack/scripts/bootstrap.sh --test
#   OFDD_BOOTSTRAP_INSTALL_DEV=1 ./afdd_stack/scripts/bootstrap.sh --test   # pip install -e ".[dev]" first
#   OFDD_BOOTSTRAP_FRONTEND_TEST=1 ./afdd_stack/scripts/bootstrap.sh --test  # also npm lint + vitest (needs Node)
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

usage() {
  cat <<'EOF'
Open-FDD bootstrap (VOLTTRON in Docker via volttron-docker)

Usage:
  ./afdd_stack/scripts/bootstrap.sh --help

Typical flow (from open-fdd repo root):
  ./afdd_stack/scripts/bootstrap.sh --central-lab
  cd "$HOME/volttron-docker"    # or OFDD_VOLTTRON_DOCKER_DIR
  # Build image + docker compose per README: https://github.com/VOLTTRON/volttron-docker

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
  --central-lab         One shot: --compose-db + wait for Postgres + --volttron-config-stub + --write-env-defaults
                        + --write-logrotate + --verify-fdd-schema + --volttron-docker + printed next steps
  --test                Run pytest (open_fdd/tests + afdd_stack/openfdd_stack/tests) from repo root; optional frontend
                        when OFDD_BOOTSTRAP_FRONTEND_TEST=1 (npm ci, eslint, vitest). No Caddy/API compose checks.

Env (optional, for --test):
  OFDD_BOOTSTRAP_INSTALL_DEV=1   pip install -U pip setuptools wheel && pip install -e ".[dev]" before pytest
  OFDD_BOOTSTRAP_FRONTEND_TEST=1 npm ci + lint + vitest in afdd_stack/frontend (requires Node/npm)
  OFDD_PYTEST_ARGS               extra arguments passed to pytest (quoted string)

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
    # Prefer --wait (Compose v2.29+): blocks until db healthcheck passes.
    set +e
    $dc up -d --wait db
    st=$?
    set -e
    if [[ "$st" -ne 0 ]]; then
      echo "[WARN] compose up --wait exited $st (older compose?); retrying: up -d db"
      $dc up -d db
    fi
  )
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

run_volttron_config_stub() {
  local home
  home="$(volttron_home)"
  mkdir -p "$home"
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
  echo "      ./afdd_stack/scripts/bootstrap.sh --write-env-defaults"
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
  ./afdd_stack/scripts/bootstrap.sh --build-openfdd-ui
  ./afdd_stack/scripts/bootstrap.sh --write-openfdd-ui-agent-config
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
  if have_cmd docker && docker ps --format '{{.Names}}' 2>/dev/null | grep -qx 'openfdd_timescale'; then
    echo "=== Waiting for Postgres (openfdd), max 60s ==="
    local i ok=0
    for i in {1..60}; do
      if docker exec openfdd_timescale pg_isready -U postgres -d openfdd >/dev/null 2>&1; then
        ok=1
        echo "[OK]   Postgres ready after ${i}s"
        break
      fi
      if (( i % 5 == 1 )); then
        echo "[INFO] $(date -Iseconds) waiting for pg_isready ($i/60)…"
      fi
      sleep 1
    done
    if [[ "$ok" -ne 1 ]]; then
      echo "[FAIL] Postgres did not become ready in 60s. Check: docker logs openfdd_timescale"
      exit 1
    fi
  fi
  run_volttron_config_stub
  run_write_env_defaults
  run_write_logrotate
  run_verify_fdd_schema
  run_clone_volttron_docker
  echo ""
  echo "=== Next: start VOLTTRON in Docker ==="
  echo "  cd \"$VOLTTRON_DOCKER_DIR\""
  echo "  # Build the image and run compose (see README in that directory)."
  echo "  # Mount $(volttron_home) as VOLTTRON_HOME in the container if you used the stubs above."
  echo "  $0 --print-vcfg-hints"
}

any_true() {
  $DOCTOR || $VOLTTRON_DOCKER || $PRINT_PATHS || $COMPOSE_DB \
    || $BUILD_OPENFDD_UI || $WRITE_OPENFDD_UI_AGENT_CONFIG || $VOLTTRON_CONFIG_STUB \
    || $PRINT_VCFG_HINTS || $WRITE_ENV_DEFAULTS || $WRITE_LOGROTATE \
    || $VERIFY_FDD_SCHEMA || $SMOKE_FDD_LOOP || $CENTRAL_LAB || $TEST
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
$TEST && run_bootstrap_test

if ! any_true; then
  usage
fi
