#!/usr/bin/env bash
# Backup Open-FDD site state before image upgrades (run on the edge host).
#
#   cd ~/open-fdd
#   ./scripts/openfdd_site_backup.sh
#   BACKUP_ROOT=~/openfdd-backups/manual ./scripts/openfdd_site_backup.sh
#
# Backs up: workspace/ (feather, BACnet CSVs, model, auth env, logs), compose files, docker state.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

BACKUP_ROOT="${BACKUP_ROOT:-$HOME/openfdd-backups/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$BACKUP_ROOT"

COMPOSE_FILE="${COMPOSE_FILE:-}"
if [[ -z "$COMPOSE_FILE" ]]; then
  if [[ -f "$ROOT/docker-compose.yml" ]]; then
    COMPOSE_FILE="$ROOT/docker-compose.yml"
  elif [[ -f "$ROOT/docker/compose.edge.yml" ]]; then
    COMPOSE_FILE="$ROOT/docker/compose.edge.yml"
  fi
fi

echo "=== Open-FDD site backup ==="
echo "Site root:  $ROOT"
echo "Backup dir: $BACKUP_ROOT"
echo ""

if [[ -f "$COMPOSE_FILE" ]]; then
  cp -a "$COMPOSE_FILE" "$BACKUP_ROOT/docker-compose.yml.snapshot"
fi
[[ -d "$ROOT/docker" ]] && cp -a "$ROOT/docker" "$BACKUP_ROOT/docker.snapshot" 2>/dev/null || true

if command -v docker >/dev/null 2>&1 && [[ -n "$COMPOSE_FILE" ]]; then
  docker ps -a >"$BACKUP_ROOT/docker-ps-before.txt" 2>/dev/null || true
  docker compose -f "$COMPOSE_FILE" ps >"$BACKUP_ROOT/docker-compose-ps-before.txt" 2>/dev/null || true
  docker compose -f "$COMPOSE_FILE" config >"$BACKUP_ROOT/docker-compose-config-before.yml" 2>/dev/null || true
  docker compose -f "$COMPOSE_FILE" config --images >"$BACKUP_ROOT/docker-images-before.txt" 2>/dev/null || true
fi
docker volume ls >"$BACKUP_ROOT/docker-volumes-before.txt" 2>/dev/null || true

if [[ ! -d "$ROOT/workspace" ]]; then
  echo "ERROR: $ROOT/workspace not found" >&2
  exit 1
fi

ARCHIVE="$BACKUP_ROOT/workspace-full.tgz"
echo "Archiving workspace/ (may need sudo for root-owned runtime files)…"
if tar --xattrs --acls -czf "$ARCHIVE" workspace 2>/dev/null; then
  :
else
  sudo tar --xattrs --acls -czf "$ARCHIVE" workspace
  sudo chown "$USER:$USER" "$ARCHIVE"
fi

echo ""
echo "Backup saved to: $BACKUP_ROOT"
du -h "$ARCHIVE"
echo ""
echo "Critical paths inside workspace/:"
echo "  workspace/data/feather_store/     historian"
echo "  workspace/data/*.json             model, rules, FDD results"
echo "  workspace/bacnet/commissioning/   BACnet bind, points.csv"
echo "  workspace/bacnet/polls/           poll samples.csv"
echo "  workspace/auth.env.local          login secrets"
echo "  workspace/api/static/app/         dashboard bundle (if rsync'd)"
