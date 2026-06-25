#!/usr/bin/env bash
# Local React UI dev — Vite hot reload, API proxied to bridge. No Docker Rust --build.
#
#   ./scripts/openfdd_ui_dev.sh              # localhost:5173
#   ./scripts/openfdd_ui_dev.sh --lan        # 0.0.0.0:5173 for remote browser on LAN
#   ./scripts/openfdd_ui_dev.sh --build-only # sync frontend/ for Caddy :443 without starting Vite
#
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_bench_lib.sh
source "$ROOT/scripts/openfdd_bench_lib.sh"
openfdd_bench_load_env "$ROOT"

LAN=0
BUILD_ONLY=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --lan) LAN=1 ;;
    --build-only) BUILD_ONLY=1 ;;
    -h|--help)
      cat <<'EOF'
Usage: scripts/openfdd_ui_dev.sh [--lan] [--build-only]

Starts (or prepares) local React development:
  - Bridge from GHCR (no bench Rust compile)
  - Vite on :5173 with /api + /openfdd-agent proxied to :8080

  --lan         Bind Vite to 0.0.0.0 (remote browser on http://<LAN-IP>:5173)
  --build-only  npm run build → frontend/ for Caddy/production; skip Vite server
EOF
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"

echo "==> Ensure API bridge is up (GHCR image, no --build)"
if ! curl -fsS --max-time 3 http://127.0.0.1:8080/health >/dev/null 2>&1; then
  "$ROOT/scripts/openfdd_local_up.sh"
fi

echo "==> Dashboard dependencies"
if [[ -d "$ROOT/workspace/dashboard/node_modules" ]]; then
  echo "    node_modules present"
else
  (cd "$ROOT/workspace/dashboard" && npm ci)
fi

echo "==> Production bundle → frontend/ (for https:// LAN / Caddy)"
(cd "$ROOT/workspace/dashboard" && npm run build)

if [[ "$BUILD_ONLY" == "1" ]]; then
  echo "OK: frontend/ synced — use Caddy https://${LAN_IP:-127.0.0.1}/ or restart bridge mount"
  exit 0
fi

export VITE_DEV_HOST="127.0.0.1"
if [[ "$LAN" == "1" ]]; then
  export VITE_DEV_HOST="0.0.0.0"
fi

echo ""
echo "React UI dev server:"
echo "  API bridge:  http://127.0.0.1:8080"
if [[ "$LAN" == "1" && -n "$LAN_IP" ]]; then
  echo "  Vite (LAN):  http://${LAN_IP}:5173/"
  echo "  Vite (local): http://127.0.0.1:5173/"
  echo "  Firewall:    sudo ufw allow 5173/tcp  (if remote browser cannot connect)"
else
  echo "  Vite:        http://127.0.0.1:5173/"
fi
echo "  Login:       integrator + workspace/bootstrap_credentials.once.txt"
echo "  Edit files in workspace/dashboard/src/ — saves hot-reload in the browser"
echo ""

cd "$ROOT/workspace/dashboard"
exec npm run dev -- --host "$VITE_DEV_HOST"
