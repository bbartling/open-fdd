#!/bin/bash
#
# open-fdd bootstrap: full Docker stack (DB, Grafana, BACnet server, scraper, API).
#
# Usage:
#   ./scripts/bootstrap.sh            # Start full stack
#   ./scripts/bootstrap.sh --verify   # Check what's running
#   ./scripts/bootstrap.sh --minimal  # DB + Grafana only (no BACnet)
#   ./scripts/bootstrap.sh --reset-grafana  # Wipe Grafana volume (fix provisioning); restarts Grafana
#
# Prerequisite: diy-bacnet-server as sibling of open-fdd (for BACnet stack).
#

set -e
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PLATFORM_DIR="$REPO_ROOT/platform"

VERIFY_ONLY=false
MINIMAL=false
RESET_GRAFANA=false
for arg in "$@"; do
  case "$arg" in
    --verify) VERIFY_ONLY=true ;;
    --minimal) MINIMAL=true ;;
    --reset-grafana) RESET_GRAFANA=true ;;
    -h|--help) echo "Usage: $0 [--verify|--minimal|--reset-grafana]"; exit 0 ;;
  esac
done

check_prereqs() {
  command -v docker >/dev/null 2>&1 || { echo "Missing: docker"; exit 1; }
  command -v docker compose >/dev/null 2>&1 || command -v docker-compose >/dev/null 2>&1 || { echo "Missing: docker compose"; exit 1; }
}

verify() {
  echo "=== Services ==="
  docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null | head -15
  echo ""
  if docker exec openfdd_timescale pg_isready -U postgres -d openfdd 2>/dev/null; then
    echo "DB: localhost:5432/openfdd (OK)"
  else
    echo "DB: not reachable"
  fi
}

if $VERIFY_ONLY; then
  check_prereqs
  verify
  exit 0
fi

if $RESET_GRAFANA; then
  check_prereqs
  cd "$PLATFORM_DIR"
  echo "=== Resetting Grafana (wipe volume, re-apply provisioning) ==="
  docker compose stop grafana 2>/dev/null || true
  docker compose rm -f grafana 2>/dev/null || true
  vol=$(docker volume ls -q | grep grafana_data | head -1)
  [[ -n "$vol" ]] && docker volume rm "$vol" || true
  echo "Starting Grafana with fresh provisioning..."
  docker compose up -d grafana
  echo "Done. Open http://localhost:3000 (admin/admin)"
  exit 0
fi

check_prereqs
cd "$PLATFORM_DIR"

if $MINIMAL; then
  echo "=== Starting minimal stack (DB + Grafana) ==="
  docker compose up -d db grafana
else
  echo "=== Building and starting full stack ==="
  docker compose up -d --build
fi

cd "$REPO_ROOT"

echo "=== Waiting for Postgres (~15s) ==="
for i in $(seq 1 30); do
  if docker exec openfdd_timescale pg_isready -U postgres -d openfdd 2>/dev/null; then
    echo "Postgres ready"
    break
  fi
  sleep 1
  [[ $i -eq 30 ]] && { echo "Postgres failed to start"; exit 1; }
done

echo "=== Applying migrations (idempotent; safe for existing DBs) ==="
(cd "$PLATFORM_DIR" && docker compose exec -T db psql -U postgres -d openfdd -f - < sql/004_fdd_input.sql) 2>/dev/null || true
(cd "$PLATFORM_DIR" && docker compose exec -T db psql -U postgres -d openfdd -f - < sql/005_bacnet_points.sql) 2>/dev/null || true
(cd "$PLATFORM_DIR" && docker compose exec -T db psql -U postgres -d openfdd -f - < sql/006_host_metrics.sql) 2>/dev/null || true

echo ""
echo "=== Bootstrap complete ==="
echo "  DB:       localhost:5432/openfdd  (postgres/postgres)"
echo "  Grafana:  http://localhost:3000   (admin/admin)"
if ! $MINIMAL; then
  echo "  API:      http://localhost:8000   (docs: /docs)"
  echo "  BACnet:   http://localhost:8080   (diy-bacnet-server Swagger)"
fi
echo ""
echo "View logs: docker compose -f platform/docker-compose.yml logs -f"
echo ""
