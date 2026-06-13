#!/usr/bin/env bash
# OpenFDD RCx Central Dash (analyst workstation — not edge).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
source "$ROOT/scripts/lib/free_port.sh"

PORT="${OPENFDD_RCX_DASH_PORT:-8050}"
free_port "$PORT" "OpenFDD RCx Central Dash"

if [[ -d .venv ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi
pip install -q -r portfolio/requirements.txt
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
export OPENFDD_CENTRAL_API_URL="${OPENFDD_CENTRAL_API_URL:-http://127.0.0.1:8060}"
export OPENFDD_DISPLAY_TZ="${OPENFDD_DISPLAY_TZ:-America/Denver}"
exec python -m portfolio.dash
