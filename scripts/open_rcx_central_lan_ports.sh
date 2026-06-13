#!/usr/bin/env bash
# Open RCx Central Dash (:8050) and API (:8060) for LAN/Tailscale clients.
# Usage: sudo ./scripts/open_rcx_central_lan_ports.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$ROOT/scripts/open_lan_port.sh" 8050 8060
