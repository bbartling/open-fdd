#!/usr/bin/env bash
# OpenFDD RCx Central Dash (analyst workstation — not edge).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
source "$ROOT/scripts/lib/free_port.sh"

HOST="${OPENFDD_RCX_DASH_HOST:-0.0.0.0}"
PORT="${OPENFDD_RCX_DASH_PORT:-8050}"
free_port "$PORT" "OpenFDD RCx Central Dash"

if [[ -d .venv ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi
pip install -q -r portfolio/requirements.txt
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
export OPENFDD_RCX_DASH_HOST="$HOST"
export OPENFDD_RCX_DASH_PORT="$PORT"
export OPENFDD_CENTRAL_API_URL="${OPENFDD_CENTRAL_API_URL:-http://127.0.0.1:8060}"
export OPENFDD_DISPLAY_TZ="${OPENFDD_DISPLAY_TZ:-America/Denver}"
LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
TS_IP="$(ip -4 addr show tailscale0 2>/dev/null | awk '/inet / {print $2}' | cut -d/ -f1 || true)"
echo "RCx Central Dash binding ${HOST}:${PORT}"
echo "  http://127.0.0.1:${PORT}/"
[[ -n "$LAN_IP" ]] && echo "  http://${LAN_IP}:${PORT}/"
[[ -n "$TS_IP" ]] && echo "  http://${TS_IP}:${PORT}/  (Tailscale)"
if systemctl is-active --quiet ufw 2>/dev/null; then
  echo "  UFW active — if LAN browsers time out, run once: sudo ./scripts/open_lan_port.sh ${PORT} 8060"
fi
exec python -m portfolio.dash
