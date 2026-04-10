#!/usr/bin/env bash
#
# Open-F-DD — single bootstrap: VOLTTRON 9 + optional local Timescale (Docker) for SQL schema.
#
# Field data: VOLTTRON pub/sub + historian (see VOLTTRON Central / platform historian SQL driver).
# Open-F-DD engine + faults: run as VOLTTRON agents against time-series tables; helpers in openfdd_stack.volttron_bridge.
# Lab: https://github.com/bbartling/py-bacnet-stacks-playground/tree/develop/vibe_code_apps_6
#
# Env:
#   OFDD_VOLTTRON_DIR     Clone target (default: $HOME/volttron)
#   OFDD_VOLTTRON_BRANCH  Git branch (default: releases/9.x)
#   OFDD_VOLTTRON_REPO    Git URL (default: https://github.com/eclipse-volttron/volttron.git)
#
# Optional Docker (this repo only ships Timescale + init SQL for openfdd schema):
#   ./afdd_stack/scripts/bootstrap.sh --compose-db   # docker compose up -d db
#
# Optional UI + VOLTTRON Central prep:
#   ./afdd_stack/scripts/bootstrap.sh --build-openfdd-ui
#   ./afdd_stack/scripts/bootstrap.sh --write-openfdd-ui-agent-config
#   ./afdd_stack/scripts/bootstrap.sh --volttron-config-stub
#   ./afdd_stack/scripts/bootstrap.sh --print-vcfg-hints
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AFDD_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
STACK_DIR="$AFDD_ROOT/stack"
REPO_ROOT="$(cd "$AFDD_ROOT/.." && pwd)"

VOLTTRON_REPO="${OFDD_VOLTTRON_REPO:-https://github.com/eclipse-volttron/volttron.git}"
VOLTTRON_BRANCH="${OFDD_VOLTTRON_BRANCH:-releases/9.x}"
VOLTTRON_DIR="${OFDD_VOLTTRON_DIR:-$HOME/volttron}"

DOCTOR=false
CLONE=false
INSTALL_VENV=false
PRINT_PATHS=false
COMPOSE_DB=false
BUILD_OPENFDD_UI=false
WRITE_OPENFDD_UI_AGENT_CONFIG=false
VOLTTRON_CONFIG_STUB=false
PRINT_VCFG_HINTS=false

usage() {
  cat <<'EOF'
Open-F-DD bootstrap (VOLTTRON-first)

Usage:
  ./afdd_stack/scripts/bootstrap.sh --help

Options:
  --doctor              Check git, python3, monorepo paths
  --clone-volttron      Clone or update VOLTTRON into OFDD_VOLTTRON_DIR
  --install-venv        After clone: python3 -m venv $VOLTTRON_DIR/env && pip install -e $VOLTTRON_DIR
  --print-paths         Print export PYTHONPATH=... for openfdd_stack imports
  --compose-db          Optional: docker compose -f afdd_stack/stack/docker-compose.yml up -d db
  --build-openfdd-ui    npm ci + vite build (afdd_stack/frontend); use VITE_BASE_PATH=/openfdd/ for Central subpath
  --write-openfdd-ui-agent-config
                        Write afdd_stack/volttron_agents/openfdd_central_ui/agent-config.json → frontend/dist
  --volttron-config-stub
                        If \$VOLTTRON_HOME/config is missing, write a minimal [volttron] stub (web + zmq lab defaults)
  --print-vcfg-hints    Print how to run vcfg for VolttronCentral + VolttronCentralPlatform + this UI agent

Then (manual):
  export VOLTTRON_HOME=${VOLTTRON_HOME:-$HOME/.volttron}
  cd "$VOLTTRON_DIR" && source env/bin/activate
  # volttron -vv -l volttron.log &   vctl status   …

EOF
}

have_cmd() { command -v "$1" >/dev/null 2>&1; }

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
  (cd "$STACK_DIR" && $dc up -d db)
  echo "DB: postgresql://postgres:postgres@127.0.0.1:5432/openfdd"
}

run_doctor() {
  echo "=== Open-F-DD VOLTTRON bootstrap doctor (read-only) ==="
  echo ""
  local fail=0
  if have_cmd git; then
    echo "[OK]   git: $(git --version 2>/dev/null | head -1)"
  else
    echo "[FAIL] git not found (needed for --clone-volttron)"
    fail=1
  fi
  if have_cmd python3; then
    echo "[OK]   python3: $(python3 --version 2>/dev/null | head -1)"
  else
    echo "[FAIL] python3 not found"
    fail=1
  fi
  echo "[INFO] uname: $(uname -a 2>/dev/null || true)"
  echo "[INFO] OFDD_VOLTTRON_DIR=$VOLTTRON_DIR"
  echo "[INFO] OFDD_VOLTTRON_BRANCH=$VOLTTRON_BRANCH"
  echo "[INFO] open-fdd monorepo: $REPO_ROOT"
  echo "[INFO] afdd_stack: $AFDD_ROOT"
  if [[ -d "$REPO_ROOT/afdd_stack/openfdd_stack/volttron_bridge" ]]; then
    echo "[OK]   volttron_bridge package present"
  else
    echo "[WARN] volttron_bridge not found"
  fi
  echo ""
  if [[ "$fail" -gt 0 ]]; then
    echo "Doctor: fix failures above."
    exit 1
  fi
  echo "Doctor: OK."
  exit 0
}

run_clone() {
  have_cmd git || {
    echo "git required"
    exit 1
  }
  if [[ -d "$VOLTTRON_DIR/.git" ]]; then
    echo "=== Updating existing VOLTTRON repo: $VOLTTRON_DIR ==="
    git -C "$VOLTTRON_DIR" fetch --all --prune || true
    git -C "$VOLTTRON_DIR" checkout "$VOLTTRON_BRANCH" 2>/dev/null || {
      echo "Branch $VOLTTRON_BRANCH not found; trying main/develop (set OFDD_VOLTTRON_BRANCH)."
      git -C "$VOLTTRON_DIR" checkout main 2>/dev/null || git -C "$VOLTTRON_DIR" checkout develop
    }
    git -C "$VOLTTRON_DIR" pull --ff-only || true
  else
    echo "=== Cloning VOLTTRON → $VOLTTRON_DIR (branch $VOLTTRON_BRANCH) ==="
    mkdir -p "$(dirname "$VOLTTRON_DIR")"
    if ! git clone --branch "$VOLTTRON_BRANCH" --depth 1 "$VOLTTRON_REPO" "$VOLTTRON_DIR"; then
      echo "Clone with branch failed; shallow clone default branch then checkout..."
      git clone --depth 1 "$VOLTTRON_REPO" "$VOLTTRON_DIR"
      git -C "$VOLTTRON_DIR" fetch --depth 1 origin "$VOLTTRON_BRANCH" && git -C "$VOLTTRON_DIR" checkout FETCH_HEAD || {
        echo "Could not obtain $VOLTTRON_BRANCH; stay on default branch and set OFDD_VOLTTRON_BRANCH."
      }
    fi
  fi
  echo "Done. VOLTTRON tree: $VOLTTRON_DIR"
}

run_install_venv() {
  [[ -d "$VOLTTRON_DIR" ]] || {
    echo "Run --clone-volttron first or set OFDD_VOLTTRON_DIR to an existing VOLTTRON tree."
    exit 1
  }
  have_cmd python3 || {
    echo "python3 required"
    exit 1
  }
  echo "=== venv + editable install in $VOLTTRON_DIR ==="
  python3 -m venv "$VOLTTRON_DIR/env"
  # shellcheck disable=SC1090
  source "$VOLTTRON_DIR/env/bin/activate"
  pip install -U pip wheel
  pip install -e "$VOLTTRON_DIR"
  echo "Activate later: source $VOLTTRON_DIR/env/bin/activate"
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
  (cd "$REPO_ROOT/afdd_stack/frontend" && npm ci && VITE_BASE_PATH="${VITE_BASE_PATH:-/openfdd/}" npm run build)
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
  local home="${VOLTTRON_HOME:-$HOME/.volttron}"
  mkdir -p "$home"
  if [[ -f "$home/config" ]]; then
    echo "[SKIP] $home/config already exists (remove it first if you want a stub)"
    return 0
  fi
  local inst="${OFDD_VOLTTRON_INSTANCE_NAME:-openfdd-edge}"
  local bind="${OFDD_VOLTTRON_BIND_WEB:-http://127.0.0.1:8443}"
  cat >"$home/config" <<EOF
[volttron]
instance-name = $inst
message-bus = zmq
vip-address = tcp://127.0.0.1:22916
bind-web-address = $bind
EOF
  echo "Wrote stub $home/config (instance-name=$inst bind-web-address=$bind)"
  echo "Next: cd \"\$VOLTTRON_DIR\" && source env/bin/activate && vcfg"
}

run_print_vcfg_hints() {
  cat <<'EOF'
=== VOLTTRON Central + Platform (vcfg) ===

1) Web-enabled instance (bind-web-address), then install VolttronCentral on the hub.
2) On each edge platform: VolttronCentralPlatform + historian + platform driver (vcfg prompts).
3) Build Open-F-DD UI:  ./afdd_stack/scripts/bootstrap.sh --build-openfdd-ui
4) Agent config:        ./afdd_stack/scripts/bootstrap.sh --write-openfdd-ui-agent-config
5) Install UI agent:   see afdd_stack/volttron_agents/openfdd_central_ui/README.md

Official walkthrough:
  https://volttron.readthedocs.io/en/main/deploying-volttron/multi-platform/volttron-central-deployment.html

Open-F-DD UI is served at /openfdd/ (build with VITE_BASE_PATH=/openfdd/). Central UI stays at /vc/ (upstream default).
EOF
}

if [[ $# -eq 0 ]]; then
  usage
  exit 0
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h | --help) usage; exit 0 ;;
    --doctor) DOCTOR=true ;;
    --clone-volttron) CLONE=true ;;
    --install-venv) INSTALL_VENV=true ;;
    --print-paths) PRINT_PATHS=true ;;
    --compose-db) COMPOSE_DB=true ;;
    --build-openfdd-ui) BUILD_OPENFDD_UI=true ;;
    --write-openfdd-ui-agent-config) WRITE_OPENFDD_UI_AGENT_CONFIG=true ;;
    --volttron-config-stub) VOLTTRON_CONFIG_STUB=true ;;
    --print-vcfg-hints) PRINT_VCFG_HINTS=true ;;
    *)
      echo "Unknown option: $1"
      usage
      exit 1
      ;;
  esac
  shift
done

$DOCTOR && run_doctor
$CLONE && run_clone
$INSTALL_VENV && run_install_venv
$PRINT_PATHS && run_print_paths
$COMPOSE_DB && run_compose_db
$BUILD_OPENFDD_UI && run_build_openfdd_ui
$WRITE_OPENFDD_UI_AGENT_CONFIG && run_write_openfdd_ui_agent_config
$VOLTTRON_CONFIG_STUB && run_volttron_config_stub
$PRINT_VCFG_HINTS && run_print_vcfg_hints

if ! $DOCTOR && ! $CLONE && ! $INSTALL_VENV && ! $PRINT_PATHS && ! $COMPOSE_DB \
  && ! $BUILD_OPENFDD_UI && ! $WRITE_OPENFDD_UI_AGENT_CONFIG && ! $VOLTTRON_CONFIG_STUB \
  && ! $PRINT_VCFG_HINTS; then
  usage
fi
