#!/usr/bin/env bash
# Remote dial-in: safe startup (no Docker rebuild) + Caddy + health check.
#
#   ./scripts/openfdd_remote_up.sh
#
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_bench_lib.sh
source "$ROOT/scripts/openfdd_bench_lib.sh"
openfdd_bench_load_env "$ROOT"
LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"

echo "==> Preflight: disk + Docker cleanup (no container stop)"
"$ROOT/scripts/openfdd_docker_maintenance.sh"

if ! docker image inspect open-fdd-openfdd-bridge:local >/dev/null 2>&1; then
  echo "==> No local bridge image — pull from GHCR (GitHub Actions build, not bench compile)"
  "$ROOT/scripts/openfdd_bench_pull_ghcr.sh"
fi

echo "==> Dashboard build (fast — no Docker image rebuild)"
if [[ -d "$ROOT/workspace/dashboard/node_modules" ]]; then
  (cd "$ROOT/workspace/dashboard" && npm run build)
else
  (cd "$ROOT/workspace/dashboard" && npm ci && npm run build)
fi

echo "==> Bridge (reuse existing image — no --build)"
"$ROOT/scripts/openfdd_local_up.sh"

echo "==> Caddy remote ingress"
"$ROOT/scripts/openfdd_local_caddy_up.sh" --mode tls ${LAN_IP:+--lan-ip "$LAN_IP"}

echo "==> Health check"
"$ROOT/scripts/openfdd_health_check.sh" --remote --auth

echo ""
echo "Remote UI:"
if [[ -n "$LAN_IP" ]]; then
  echo "  https://${LAN_IP}/"
fi
echo "  http://127.0.0.1:8080/  (local only)"
echo ""
echo "Login: integrator + password from workspace/bootstrap_credentials.once.txt"
echo "Quick check: ./scripts/openfdd_health_check.sh --remote --auth"
