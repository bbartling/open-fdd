#!/usr/bin/env bash
# Shared helpers for openfdd_site_backup.sh and openfdd_site_update.sh.
# Source from other scripts; not executed directly.
set -euo pipefail

openfdd_site_root_from_caller() {
  local caller="${BASH_SOURCE[1]:-${BASH_SOURCE[0]}}"
  cd "$(dirname "$caller")/.." && pwd
}

# Docker image platform: auto-detect host CPU unless OPENFDD_DOCKER_PLATFORM is set.
# Values: auto (default), linux/arm64, linux/amd64, or aliases arm64|amd64|aarch64|x86_64.
openfdd_detect_docker_platform() {
  case "$(uname -m)" in
    aarch64|arm64) echo "linux/arm64" ;;
    x86_64|amd64) echo "linux/amd64" ;;
    *) echo "linux/$(uname -m)" ;;
  esac
}

openfdd_normalize_docker_platform() {
  local raw="${1:-auto}"
  case "$raw" in
    ""|auto) openfdd_detect_docker_platform ;;
    linux/arm64|arm64|aarch64) echo "linux/arm64" ;;
    linux/amd64|amd64|x86_64) echo "linux/amd64" ;;
    linux/*) echo "$raw" ;;
    *)
      echo "ERROR: unknown platform: $raw (use auto, linux/arm64, or linux/amd64)" >&2
      return 1
      ;;
  esac
}

openfdd_resolve_docker_platform() {
  openfdd_normalize_docker_platform "${OPENFDD_DOCKER_PLATFORM:-auto}"
}

openfdd_platform_arch() {
  local platform="${1:-}"
  if [[ -z "$platform" ]]; then
    platform="$(openfdd_resolve_docker_platform)" || return 1
  fi
  printf '%s' "${platform#linux/}"
}

openfdd_export_docker_platform() {
  local platform
  platform="$(openfdd_resolve_docker_platform)" || return 1
  export OPENFDD_DOCKER_PLATFORM="$platform"
  export DOCKER_DEFAULT_PLATFORM="$platform"
  printf '%s' "$platform"
}

openfdd_resolve_compose_file() {
  local root="$1"
  local compose="${COMPOSE_FILE:-}"
  if [[ -z "$compose" ]]; then
    if [[ -f "$root/docker-compose.yml" ]]; then
      compose="$root/docker-compose.yml"
    elif [[ -f "$root/docker/compose.edge.yml" ]]; then
      compose="$root/docker/compose.edge.yml"
    fi
  fi
  printf '%s' "$compose"
}

openfdd_safe_docker_maintenance() {
  local prune_unused="${PRUNE_UNUSED_IMAGES:-1}"
  local prune_cache="${PRUNE_BUILD_CACHE:-0}"

  echo "==> Safe Docker maintenance (never volume prune)"
  if ! command -v docker >/dev/null 2>&1; then
    echo "WARN: docker not installed — skipping maintenance" >&2
    return 0
  fi

  docker system df 2>/dev/null || true
  docker container prune -f 2>/dev/null || true
  docker network prune -f 2>/dev/null || true
  docker image prune -f 2>/dev/null || true

  if [[ "$prune_cache" == "1" ]]; then
    docker builder prune -f --filter "until=168h" 2>/dev/null \
      || docker builder prune -f 2>/dev/null || true
  fi

  if [[ "$prune_unused" == "1" ]]; then
    echo "==> Prune unused images (not referenced by running containers)"
    docker image prune -a -f 2>/dev/null || true
  fi

  docker system df 2>/dev/null || true
}

openfdd_backup_archive_path() {
  local backup_root="$1"
  printf '%s/workspace-full.tgz' "$backup_root"
}

openfdd_backup_manifest_path() {
  local backup_root="$1"
  printf '%s/backup-manifest.txt' "$backup_root"
}

openfdd_validate_backup_archive() {
  local archive="$1"
  if [[ ! -f "$archive" ]]; then
    echo "ERROR: backup archive not found: $archive" >&2
    return 1
  fi
  if ! tar -tzf "$archive" workspace >/dev/null 2>&1; then
    echo "ERROR: backup archive failed integrity check (missing workspace/): $archive" >&2
    return 1
  fi
  echo "Backup archive OK: $archive ($(du -h "$archive" | awk '{print $1}'))"
}

openfdd_apply_feather_restore_cap() {
  local feather_root="$1"
  local max_gib="${2:-0}"

  if [[ -z "$max_gib" || "$max_gib" == "0" ]]; then
    echo "Feather restore cap: disabled (restore all historian data)"
    return 0
  fi
  if [[ ! -d "$feather_root" ]]; then
    echo "Feather restore cap: no feather_store at $feather_root — skip"
    return 0
  fi

  local max_bytes
  max_bytes=$(awk -v gib="$max_gib" 'BEGIN { printf "%.0f", gib * 1024 * 1024 * 1024 }')
  local total
  total=$(du -sb "$feather_root" 2>/dev/null | awk '{print $1}')
  if [[ -z "$total" || "$total" -le "$max_bytes" ]]; then
    echo "Feather store within ${max_gib} GiB cap ($(numfmt --to=iec-i --suffix=B "$total" 2>/dev/null || echo "${total} bytes"))"
    return 0
  fi

  echo "Feather store $(numfmt --to=iec-i --suffix=B "$total" 2>/dev/null || echo "$total bytes") exceeds ${max_gib} GiB — dropping oldest shards…"

  # Oldest shards first (by mtime); delete until under cap.
  while IFS= read -r line; do
    path="${line#* }"
    [[ -f "$path" ]] || continue
    total=$(du -sb "$feather_root" 2>/dev/null | awk '{print $1}')
    [[ "$total" -le "$max_bytes" ]] && break
    size=$(stat -c '%s' "$path" 2>/dev/null || echo 0)
    rm -f "$path"
    echo "  removed $(basename "$path")"
    total=$(( total - size ))
  done < <(find "$feather_root" -type f -name 'shard-*.feather' -printf '%T@ %p\n' 2>/dev/null | sort -n)

  total=$(du -sb "$feather_root" 2>/dev/null | awk '{print $1}')
  if [[ "$total" -gt "$max_bytes" ]]; then
    echo "WARN: feather_store still above ${max_gib} GiB after shard prune — large latest.feather may need runtime trim (OFDD_FEATHER_MAX_GIB)" >&2
  else
    echo "Feather store now within ${max_gib} GiB cap"
  fi
}

openfdd_restore_workspace_from_backup() {
  local backup_root="$1"
  local root="$2"
  local feather_max_gib="${3:-200}"

  local archive manifest staging
  archive="$(openfdd_backup_archive_path "$backup_root")"
  manifest="$(openfdd_backup_manifest_path "$backup_root")"

  openfdd_validate_backup_archive "$archive"

  staging="${root}/.openfdd-restore-staging-$$"
  mkdir -p "$staging"
  trap 'rm -rf "$staging"' RETURN

  echo "==> Extract backup to staging"
  tar -xzf "$archive" -C "$staging"

  if [[ ! -d "$staging/workspace" ]]; then
    echo "ERROR: extracted archive missing workspace/" >&2
    return 1
  fi

  openfdd_apply_feather_restore_cap "$staging/workspace/data/feather_store" "$feather_max_gib"

  echo "==> Restore workspace/ from backup"
  mkdir -p "$root/workspace"
  if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete "$staging/workspace/" "$root/workspace/"
  else
    rm -rf "${root:?}/workspace"
    cp -a "$staging/workspace" "$root/workspace"
  fi

  if [[ -f "$manifest" ]]; then
    cp -a "$manifest" "$root/workspace/.last-restore-manifest.txt" 2>/dev/null || true
  fi

  rm -rf "$staging"
  trap - RETURN
  echo "Workspace restore complete"
}

openfdd_validate_workspace_layout() {
  local root="$1"
  local ok=0

  for path in workspace workspace/data workspace/bacnet/commissioning; do
    if [[ ! -d "$root/$path" ]]; then
      echo "WARN: missing $root/$path" >&2
      ok=1
    fi
  done

  if [[ -f "$root/workspace/auth.env.local" ]]; then
    echo "  auth.env.local present"
  else
    echo "WARN: workspace/auth.env.local missing" >&2
    ok=1
  fi

  return "$ok"
}

openfdd_validate_site_health() {
  local health_url="${1:-http://127.0.0.1:8765/health}"
  if curl -sf --connect-timeout 10 "$health_url" >/dev/null; then
    echo "Bridge health OK: $health_url"
    return 0
  fi
  echo "WARN: bridge health check failed: $health_url" >&2
  return 1
}

openfdd_purge_backup_dir() {
  local backup_root="$1"
  if [[ -z "$backup_root" || ! -d "$backup_root" ]]; then
    echo "No backup dir to purge: ${backup_root:-<unset>}"
    return 0
  fi
  echo "==> Purge validated backup: $backup_root"
  rm -rf "$backup_root"
  if [[ -d "$backup_root" ]]; then
    echo "ERROR: failed to remove backup dir: $backup_root" >&2
    return 1
  fi
  echo "Backup removed after successful validation"
}
