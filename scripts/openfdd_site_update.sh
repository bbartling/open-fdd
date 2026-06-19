#!/usr/bin/env bash
# Pull new GHCR images, safe Docker maintenance, optional workspace restore, validate, purge backup.
#
# Typical upgrade (workspace bind-mount preserved):
#   cd ~/open-fdd
#   ./scripts/openfdd_site_backup.sh
#   ./scripts/openfdd_site_update.sh
#
# Disaster recovery / intentional full restore from latest backup:
#   RESTORE_WORKSPACE=1 ./scripts/openfdd_site_update.sh
#
# Restore all historian data (no 200 GiB feather cap):
#   RESTORE_WORKSPACE=1 RESTORE_FEATHER_MAX_GIB=0 ./scripts/openfdd_site_update.sh
#
# Env:
#   NEW_TAG / OPENFDD_IMAGE_TAG     Image tag (default: latest)
#   BACKUP_ROOT                     Backup dir (default: ~/openfdd-backups/latest)
#   SKIP_DOCKER_MAINTENANCE=1         Skip image/container prune
#   RESTORE_WORKSPACE=0|1           Extract backup over workspace/ (default: 0)
#   RESTORE_FEATHER_MAX_GIB=200       Cap historian on restore; 0 = restore all feather
#   PURGE_BACKUP_AFTER_SUCCESS=1      Delete BACKUP_ROOT after validation (default: 1)
#   REQUIRE_BACKUP=1                  Fail if backup missing (default: 1 when PURGE=1)
#
# Never runs: docker compose down -v, docker volume prune, or workspace deletion without restore.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=openfdd_site_lib.sh
source "$ROOT/scripts/openfdd_site_lib.sh"
cd "$ROOT"

NEW_TAG="${NEW_TAG:-${OPENFDD_IMAGE_TAG:-latest}}"
BACKUP_ROOT="${BACKUP_ROOT:-$HOME/openfdd-backups/latest}"
SKIP_DOCKER_MAINTENANCE="${SKIP_DOCKER_MAINTENANCE:-0}"
RESTORE_WORKSPACE="${RESTORE_WORKSPACE:-0}"
RESTORE_FEATHER_MAX_GIB="${RESTORE_FEATHER_MAX_GIB:-200}"
PURGE_BACKUP_AFTER_SUCCESS="${PURGE_BACKUP_AFTER_SUCCESS:-1}"
REQUIRE_BACKUP="${REQUIRE_BACKUP:-$PURGE_BACKUP_AFTER_SUCCESS}"

COMPOSE_FILE="$(openfdd_resolve_compose_file "$ROOT")"
if [[ -z "$COMPOSE_FILE" ]]; then
  echo "No docker-compose.yml or docker/compose.edge.yml found under $ROOT" >&2
  exit 1
fi

export OPENFDD_IMAGE_TAG="$NEW_TAG"
COMPOSE=(docker compose -f "$COMPOSE_FILE")

IMAGES=(
  "ghcr.io/bbartling/openfdd-bridge:${NEW_TAG}"
  "ghcr.io/bbartling/openfdd-commission:${NEW_TAG}"
  "ghcr.io/bbartling/openfdd-mcp-rag:${NEW_TAG}"
)

ARCHIVE="$(openfdd_backup_archive_path "$BACKUP_ROOT")"

echo "=== Open-FDD site update → ${NEW_TAG} ==="
echo "Compose file:     $COMPOSE_FILE"
echo "Backup root:        $BACKUP_ROOT"
echo "Restore workspace: $RESTORE_WORKSPACE"
echo "Feather cap (GiB):  $([[ "$RESTORE_WORKSPACE" == "1" ]] && echo "${RESTORE_FEATHER_MAX_GIB} (0=all)" || echo n/a)"
echo "Purge backup OK:    $PURGE_BACKUP_AFTER_SUCCESS"
echo ""

if [[ "$REQUIRE_BACKUP" == "1" ]]; then
  if [[ ! -f "$ARCHIVE" ]]; then
    echo "ERROR: backup not found — run ./scripts/openfdd_site_backup.sh first" >&2
    echo "       expected: $ARCHIVE" >&2
    exit 1
  fi
  openfdd_validate_backup_archive "$ARCHIVE"
elif [[ -f "$ARCHIVE" ]]; then
  openfdd_validate_backup_archive "$ARCHIVE" || true
else
  echo "WARN: no backup at $ARCHIVE (REQUIRE_BACKUP=0)" >&2
fi

if [[ "$SKIP_DOCKER_MAINTENANCE" != "1" ]]; then
  openfdd_safe_docker_maintenance
  echo ""
fi

echo "==> Verify images exist on GHCR"
for img in "${IMAGES[@]}"; do
  docker manifest inspect "$img" >/dev/null
  echo "  OK $img"
done

if [[ -f "$ROOT/docker-compose.yml" ]] && grep -q 'OPENFDD_IMAGE_TAG\|2026\.[0-9]' "$ROOT/docker-compose.yml" 2>/dev/null; then
  cp "$ROOT/docker-compose.yml" "$ROOT/docker-compose.yml.bak.$(date +%Y%m%d-%H%M%S)"
  if grep -q 'ghcr.io/bbartling/openfdd-bridge:' "$ROOT/docker-compose.yml"; then
    sed -i -E "s|(ghcr.io/bbartling/openfdd-[a-z-]+):[^\"'[:space:]]+|\1:${NEW_TAG}|g" "$ROOT/docker-compose.yml"
    echo "Updated image tags in docker-compose.yml"
  fi
fi

if [[ "$RESTORE_WORKSPACE" == "1" ]]; then
  echo ""
  echo "==> Stop stack before workspace restore"
  "${COMPOSE[@]}" stop 2>/dev/null || true
  openfdd_restore_workspace_from_backup "$BACKUP_ROOT" "$ROOT" "$RESTORE_FEATHER_MAX_GIB"
  echo ""
fi

echo "==> Pull and recreate"
"${COMPOSE[@]}" pull
"${COMPOSE[@]}" up -d --force-recreate

echo ""
echo "==> Container status"
"${COMPOSE[@]}" ps
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}' | grep -E 'openfdd|NAMES' || true

echo ""
echo "==> Post-update validation"
VALIDATION_OK=1
openfdd_validate_workspace_layout "$ROOT" || VALIDATION_OK=0
openfdd_validate_site_health "http://127.0.0.1:8765/health" || VALIDATION_OK=0

if [[ "$VALIDATION_OK" != "1" ]]; then
  echo ""
  echo "ERROR: post-update validation failed — backup kept at $BACKUP_ROOT" >&2
  echo "To restore workspace from backup:" >&2
  echo "  RESTORE_WORKSPACE=1 BACKUP_ROOT=$BACKUP_ROOT ./scripts/openfdd_site_update.sh" >&2
  exit 1
fi

if [[ "$PURGE_BACKUP_AFTER_SUCCESS" == "1" && -d "$BACKUP_ROOT" ]]; then
  echo ""
  openfdd_purge_backup_dir "$BACKUP_ROOT"
fi

echo ""
echo "Done. BACnet poll resumes when commission container is healthy."
echo "Optional logs: docker compose -f $COMPOSE_FILE logs --since 10m"
