#!/usr/bin/env bash
# Local React UI dev — Vite hot reload, API proxied to central :8080.
#
#   ./scripts/openfdd_ui_dev.sh              # localhost:5173
#   ./scripts/openfdd_ui_dev.sh --lan        # 0.0.0.0:5173 for remote browser on LAN
#   ./scripts/openfdd_ui_dev.sh --build-only # build UI dist only
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

LAN=0
BUILD_ONLY=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --lan) LAN=1 ;;
    --build-only) BUILD_ONLY=1 ;;
    -h|--help)
      cat <<'EOF'
Usage: scripts/openfdd_ui_dev.sh [--lan] [--build-only]

  --lan         Bind Vite to 0.0.0.0
  --build-only  npm run build → workspace/dashboard/dist; skip Vite server
EOF
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

cd "$ROOT/workspace/dashboard"
npm ci

if [[ "$BUILD_ONLY" -eq 1 ]]; then
  VITE_OUT_DIR=dist npm run build
  test -f dist/index.html
  echo "OK built workspace/dashboard/dist"
  exit 0
fi

export VITE_DEV_HOST="127.0.0.1"
[[ "$LAN" -eq 1 ]] && export VITE_DEV_HOST="0.0.0.0"
echo "==> Vite on http://${VITE_DEV_HOST}:5173 (proxy /api → :8080)"
echo "    Start central first: ./scripts/openfdd_stack_up.sh csv   # or standalone"
npm run dev
