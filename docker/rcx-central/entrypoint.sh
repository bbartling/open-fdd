#!/usr/bin/env bash
set -euo pipefail
MODE="${1:-api}"
case "$MODE" in
  api)
    exec python3 -m portfolio.central
    ;;
  dash)
    exec python3 -m portfolio.dash
    ;;
  both)
    python3 -m portfolio.central &
    exec python3 -m portfolio.dash
    ;;
  *)
    echo "Usage: entrypoint.sh [api|dash|both]" >&2
    exit 1
    ;;
esac
