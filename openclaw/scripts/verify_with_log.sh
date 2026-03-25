#!/usr/bin/env bash
# Agent-safe: run bootstrap --verify with a timestamped log (no manual ts= in nested shells).
# From anywhere:  openclaw/scripts/verify_with_log.sh
# Requires: repo layout open-fdd/openclaw/scripts/thisfile → finds repo root automatically.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$SCRIPT_DIR/capture_bootstrap_log.sh" --verify
