#!/usr/bin/env bash
# Pull new GHCR images, safe Docker maintenance, optional workspace restore, validate, purge backup.
#
# Typical upgrade, workspace bind-mount preserved:
#   cd ~/open-fdd
#   ./scripts/openfdd_site_backup.sh
#   ./scripts/openfdd_site_update.sh
#
# Disaster recovery / intentional full restore from latest backup:
#   RESTORE_WORKSPACE=1 ./scripts/openfdd_site_update.sh
#
# Restore all historian data, no 200 GiB feather cap:
#   RESTORE_WORKSPACE=1 RESTORE_FEATHER_MAX_GIB=0 ./scripts/openfdd_site_update.sh
#
# Env:
#   NEW_TAG / OPENFDD_IMAGE_TAG       Image tag, default latest
#   OPENFDD_DOCKER_PLATFORM          auto, linux/arm64, linux/amd64
#   BACKUP_ROOT                      Backup dir, default ~/openfdd-backups/latest
#   SKIP_DOCKER_MAINTENANCE=1        Skip image/container prune
#   RESTORE_WORKSPACE=0|1            Extract backup over workspace/, default 0
#   RESTORE_FEATHER_MAX_GIB=200      Cap historian on restore; 0 = restore all feather
#   PURGE_BACKUP_AFTER_SUCCESS=1     Delete BACKUP_ROOT after validation, default 1
#   REQUIRE_BACKUP=1                 Fail if backup missing, default follows PURGE_BACKUP_AFTER_SUCCESS
#   OPENFDD_HEALTH_TIMEOUT_SECS=120  Health wait timeout
#
# Never runs:
#   docker compose down -v
#   docker volume prune
#   docker system prune --volumes
#   workspace deletion without RESTORE_WORKSPACE=1
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

export OPENFDD_IMAGE_TAG="$NEW_TAG"
export OPENFDD_UID="${OPENFDD_UID:-$(id -u)}"
export OPENFDD_GID="${OPENFDD_GID:-$(id -g)}"

COMPOSE_FILE="$(openfdd_resolve_compose_file "$ROOT")"
if [[ -z "$COMPOSE_FILE" ]]; then
  echo "No docker-compose.yml or docker/compose.edge.yml found under $ROOT" >&2
  exit 1
fi

COMPOSE=(docker compose -f "$COMPOSE_FILE")

IMAGES=(
  "ghcr.io/bbartling/openfdd-bridge:${NEW_TAG}"
  "ghcr.io/bbartling/openfdd-commission:${NEW_TAG}"
  "ghcr.io/bbartling/openfdd-mcp-rag:${NEW_TAG}"
)

ARCHIVE="$(openfdd_backup_archive_path "$BACKUP_ROOT")"

echo "=== Open-FDD site update → ${NEW_TAG} ==="
PLATFORM="$(openfdd_export_docker_platform)"
echo "Compose file:       $COMPOSE_FILE"
echo "Docker platform:    ${PLATFORM} (host $(uname -m))"
echo "Image tag:          $NEW_TAG"
echo "OPENFDD_UID:GID:    ${OPENFDD_UID}:${OPENFDD_GID}"
echo "Backup root:        $BACKUP_ROOT"
echo "Restore workspace:  $RESTORE_WORKSPACE"
echo "Feather cap (GiB):  $([[ "$RESTORE_WORKSPACE" == "1" ]] && echo "${RESTORE_FEATHER_MAX_GIB} (0=all)" || echo n/a)"
echo "Purge backup OK:    $PURGE_BACKUP_AFTER_SUCCESS"
echo ""

openfdd_warn_plaintext_passwords "$ROOT" || true
openfdd_report_root_owned_workspace_files "$ROOT" || true

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
  echo ""
  openfdd_safe_docker_maintenance
  echo ""
fi

echo "==> Verify images exist on GHCR (${PLATFORM})"
if [[ -x "$ROOT/scripts/openfdd_check_ghcr_platform.sh" ]]; then
  OPENFDD_IMAGE_TAG="$NEW_TAG" OPENFDD_DOCKER_PLATFORM="$PLATFORM" \
    "$ROOT/scripts/openfdd_check_ghcr_platform.sh"
else
  for img in "${IMAGES[@]}"; do
    docker manifest inspect "$img" >/dev/null
    echo "  OK $img"
  done
fi

echo ""
echo "==> Parameterize compose image tags"
openfdd_parameterize_compose_images "$COMPOSE_FILE"

echo ""
echo "==> Verify compose resolves requested tag"
openfdd_assert_compose_uses_tag "$COMPOSE_FILE" "$NEW_TAG"

if [[ "$RESTORE_WORKSPACE" == "1" ]]; then
  echo ""
  echo "==> Stop stack before workspace restore"
  "${COMPOSE[@]}" stop 2>/dev/null || true
  openfdd_restore_workspace_from_backup "$BACKUP_ROOT" "$ROOT" "$RESTORE_FEATHER_MAX_GIB"
  echo ""
fi

echo ""
echo "==> Pull and recreate"
OPENFDD_IMAGE_TAG="$NEW_TAG" "${COMPOSE[@]}" pull
OPENFDD_IMAGE_TAG="$NEW_TAG" "${COMPOSE[@]}" up -d --force-recreate --remove-orphans

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
  echo "ERROR: post-update validation failed after health retry timeout — backup kept at $BACKUP_ROOT" >&2
  echo "To restore workspace from backup:" >&2
  echo "  RESTORE_WORKSPACE=1 BACKUP_ROOT=$BACKUP_ROOT ./scripts/openfdd_site_update.sh" >&2
  exit 1
fi

echo ""
echo "==> Final resolved images"
OPENFDD_IMAGE_TAG="$NEW_TAG" "${COMPOSE[@]}" config --images

echo ""
echo "==> Final health"
FINAL_HEALTH_STATUS="OK"
if ! curl -fsS http://127.0.0.1:8765/health; then
  FINAL_HEALTH_STATUS="UNREACHABLE"
  echo "WARN: final health probe failed" >&2
fi
echo ""

openfdd_warn_plaintext_passwords "$ROOT" || true
openfdd_report_root_owned_workspace_files "$ROOT" || true

if [[ "$PURGE_BACKUP_AFTER_SUCCESS" == "1" && -d "$BACKUP_ROOT" ]]; then
  echo ""
  openfdd_purge_backup_dir "$BACKUP_ROOT"
else
  echo ""
  echo "Backup retained at: $BACKUP_ROOT"
fi

echo ""
echo "Open-FDD update complete"
echo "  Tag:        $NEW_TAG"
echo "  Compose:    $COMPOSE_FILE"
echo "  Backup:     $BACKUP_ROOT"
echo "  Health:     $FINAL_HEALTH_STATUS"
echo ""
echo "Done. BACnet poll resumes when commission container is healthy."
echo "Optional logs: docker compose -f $COMPOSE_FILE logs --since 10m"