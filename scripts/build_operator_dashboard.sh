#!/usr/bin/env bash
# Build operator dashboard into workspace/api/static/app
#
#   ./scripts/build_operator_dashboard.sh          # production (default)
#   ./scripts/build_operator_dashboard.sh prod     # same as default
#   ./scripts/build_operator_dashboard.sh test     # vitest then production build
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODE="${1:-prod}"
cd "$ROOT/workspace/dashboard"
if [[ -f package-lock.json ]]; then npm ci; else npm install; fi
case "$MODE" in
  test)
    echo "==> Dashboard vitest"
    npm test
    echo "==> Dashboard production build"
    npm run build
    ;;
  prod|production)
    npm run build
    ;;
  *)
    echo "Usage: $0 [prod|test]" >&2
    exit 1
    ;;
esac
echo "Dashboard built to workspace/api/static/app"
