#!/usr/bin/env bash
# Safely update an existing Rust Open-FDD edge site (never down -v, never delete workspace).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_rust_site_lib.sh
source "$ROOT/scripts/openfdd_rust_site_lib.sh"

cd "$ROOT"
OPENFDD_IMAGE_TAG="${NEW_TAG:-${OPENFDD_IMAGE_TAG:-latest}}"
BACKUP_ROOT="${BACKUP_ROOT:-$HOME/openfdd-backups/latest}"
REQUIRE_BACKUP="${REQUIRE_BACKUP:-1}"
HEALTH_TIMEOUT="${OPENFDD_HEALTH_TIMEOUT_SECS:-120}"
DRY_RUN="${DRY_RUN:-0}"
PURGE_BACKUP="${PURGE_BACKUP_AFTER_SUCCESS:-0}"
SKIP_MAINT="${SKIP_DOCKER_MAINTENANCE:-0}"

export OPENFDD_IMAGE_TAG
PLATFORM="$(openfdd_rust_export_docker_platform)"
COMPOSE="$(openfdd_rust_resolve_compose_file "$ROOT")"

echo "==> Rust edge update (tag=${OPENFDD_IMAGE_TAG}, platform=${PLATFORM})"

openfdd_rust_check_docker

[[ -n "$COMPOSE" && -f "$COMPOSE" ]] || {
  echo "ERROR: compose file not found under $ROOT" >&2
  exit 1
}

openfdd_rust_write_site_env "$ROOT" "$OPENFDD_IMAGE_TAG"
openfdd_rust_install_edge_compose "$ROOT" "${OPENFDD_REPO_REF:-master}"

if [[ "$REQUIRE_BACKUP" == "1" ]]; then
  echo "==> Backup (required)"
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "DRY_RUN: would run openfdd_rust_site_backup.sh"
  else
    "$ROOT/scripts/openfdd_rust_site_backup.sh"
  fi
fi

if [[ "$DRY_RUN" == "1" ]]; then
  echo "DRY_RUN: docker compose -f $COMPOSE pull && up -d --force-recreate"
  exit 0
fi

docker compose -f "$COMPOSE" config >/dev/null
"$ROOT/scripts/openfdd_rust_check_ghcr_platform.sh" || echo "WARN: GHCR platform check failed — continuing with pull attempt"

echo "==> Pull and recreate containers (env files reload at create time)"
docker compose -f "$COMPOSE" pull
docker compose -f "$COMPOSE" up -d --force-recreate

openfdd_rust_wait_for_health "http://127.0.0.1:8080/api/health" "$HEALTH_TIMEOUT"
curl -fsS http://127.0.0.1:8080/api/health | jq -e '.ok == true'

AUTH="$ROOT/workspace/auth.env.local"
openfdd_rust_login_smoke "http://127.0.0.1:8080" "$AUTH"
openfdd_rust_warn_root_owned_workspace "$ROOT/workspace"

if [[ "$SKIP_MAINT" != "1" ]]; then
  openfdd_rust_safe_docker_maintenance
fi

if [[ "$PURGE_BACKUP" == "1" ]]; then
  rm -f "$(openfdd_rust_backup_archive_path "$BACKUP_ROOT")" && echo "Purged latest backup after successful update"
fi

echo "Update OK — tag ${OPENFDD_IMAGE_TAG}, platform ${PLATFORM}"
