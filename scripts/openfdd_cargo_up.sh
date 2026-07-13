#!/usr/bin/env bash
# Start Open-FDD edge + React SPA without Docker (WSL / Linux when Docker Desktop is down).
#
#   ./scripts/openfdd_cargo_up.sh           # reuse release binary if present
#   ./scripts/openfdd_cargo_up.sh --build   # cargo build --release first
#
# Requires: workspace/auth.env.local (./scripts/openfdd_auth_init.sh --show-secrets)
# UI: http://127.0.0.1:8080
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

LOG_DIR="$ROOT/workspace/logs"
LOG_FILE="$LOG_DIR/edge-dev.log"
PID_FILE="$LOG_DIR/edge-dev.pid"
BIN_RELEASE="$ROOT/target/release/open_fdd_edge_prototype"
BIN_DEBUG="$ROOT/target/debug/open_fdd_edge_prototype"
AUTH="$ROOT/workspace/auth.env.local"
BUILD=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --build) BUILD=1 ;;
    -h|--help)
      sed -n '2,10p' "$0"
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

if [[ ! -f "$AUTH" ]]; then
  echo "ERROR: missing $AUTH"
  echo "Run: ./scripts/openfdd_auth_init.sh --show-secrets"
  exit 1
fi

mkdir -p "$LOG_DIR"

need_frontend=0
if [[ ! -f "$ROOT/frontend/index.html" ]]; then
  need_frontend=1
elif [[ ! -d "$ROOT/frontend/assets" ]] || [[ -z "$(find "$ROOT/frontend/assets" -mindepth 1 -maxdepth 1 2>/dev/null | head -1)" ]]; then
  need_frontend=1
fi
if [[ "$need_frontend" -eq 1 ]]; then
  echo "==> Building React SPA → frontend/"
  (cd "$ROOT/workspace/dashboard" && npm ci && npm run build)
fi

if [[ "$BUILD" -eq 1 ]] || [[ ! -x "$BIN_RELEASE" && ! -x "$BIN_DEBUG" ]]; then
  echo "==> cargo build --release -p open_fdd_edge_prototype"
  cargo build --release -p open_fdd_edge_prototype --bin open_fdd_edge_prototype
fi

if [[ -x "$BIN_RELEASE" ]]; then
  BIN="$BIN_RELEASE"
elif [[ -x "$BIN_DEBUG" ]]; then
  echo "WARN: using debug binary (slower) — run with --build for release"
  BIN="$BIN_DEBUG"
else
  echo "ERROR: no open_fdd_edge_prototype binary found"
  exit 1
fi

if curl -fsS --max-time 2 http://127.0.0.1:8080/api/health >/dev/null 2>&1; then
  echo "==> Already healthy on :8080 — open http://127.0.0.1:8080"
  curl -fsS http://127.0.0.1:8080/api/health
  echo
  exit 0
fi

if [[ -f "$PID_FILE" ]]; then
  old="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "${old:-}" ]] && kill -0 "$old" 2>/dev/null; then
    echo "==> Stopping previous edge pid=$old"
    kill "$old" 2>/dev/null || true
    sleep 1
  fi
  rm -f "$PID_FILE"
fi

# Free stale listeners on 8080
if command -v fuser >/dev/null 2>&1; then
  fuser -k 8080/tcp 2>/dev/null || true
elif command -v lsof >/dev/null 2>&1; then
  lsof -ti:8080 | xargs -r kill 2>/dev/null || true
fi
sleep 1

export OPENFDD_WORKSPACE="${OPENFDD_WORKSPACE:-$ROOT/workspace}"
export FRONTEND_DIR="${FRONTEND_DIR:-$ROOT/frontend}"
export OPENFDD_BIND_HOST="${OPENFDD_BIND_HOST:-127.0.0.1}"
export PORT="${PORT:-8080}"
export OPENFDD_BACNET_SERVER_ENABLED="${OPENFDD_BACNET_SERVER_ENABLED:-0}"
export OPENFDD_ALLOW_INSECURE_AUTH="${OPENFDD_ALLOW_INSECURE_AUTH:-1}"

echo "==> Starting $BIN (log: $LOG_FILE)"
nohup "$BIN" >>"$LOG_FILE" 2>&1 &
echo $! >"$PID_FILE"
echo "==> pid=$(cat "$PID_FILE")"

for _ in $(seq 1 40); do
  if curl -fsS --max-time 2 http://127.0.0.1:8080/api/health >/dev/null 2>&1; then
    echo "==> Health OK — open http://127.0.0.1:8080/login"
    curl -fsS http://127.0.0.1:8080/api/health
    echo
    if [[ -f "$ROOT/workspace/bootstrap_credentials.once.txt" ]]; then
      echo "==> Bootstrap passwords: workspace/bootstrap_credentials.once.txt"
    fi
    exit 0
  fi
  sleep 1
done

echo "ERROR: edge did not become healthy — see $LOG_FILE"
tail -n 40 "$LOG_FILE" || true
exit 1
