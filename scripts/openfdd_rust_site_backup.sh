#!/usr/bin/env bash
# Backup Rust Open-FDD edge workspace (never deletes workspace).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_rust_site_lib.sh
source "$ROOT/scripts/openfdd_rust_site_lib.sh"

BACKUP_ROOT="${BACKUP_ROOT:-$HOME/openfdd-backups/latest}"
INCLUDE_HISTORIAN="${BACKUP_INCLUDE_HISTORIAN:-1}"
INCLUDE_POLL="${BACKUP_INCLUDE_POLL_SAMPLES:-1}"
TS="$(date +%Y%m%d-%H%M%S)"
ARCHIVE="$(openfdd_rust_backup_archive_path "$BACKUP_ROOT")"
STAMP_DIR="$(dirname "$ARCHIVE")/${TS}"

mkdir -p "$STAMP_DIR"
WORK="$ROOT/workspace"
[[ -d "$WORK" ]] || {
  echo "ERROR: workspace not found: $WORK" >&2
  exit 1
}

EXCLUDES=(--exclude='workspace/backups' --exclude='*.tgz')
if [[ "$INCLUDE_HISTORIAN" == "0" ]]; then
  EXCLUDES+=(--exclude='workspace/data/historian')
fi
if [[ "$INCLUDE_POLL" == "0" ]]; then
  EXCLUDES+=(--exclude='workspace/data/poll_samples')
fi

echo "==> Backing up workspace to $ARCHIVE"
tar -czf "$ARCHIVE" -C "$ROOT" "${EXCLUDES[@]}" workspace
openfdd_rust_validate_backup_archive "$ARCHIVE"
cp "$ARCHIVE" "$STAMP_DIR/workspace-full.tgz"
{
  echo "timestamp=$TS"
  echo "root=$ROOT"
  echo "include_historian=$INCLUDE_HISTORIAN"
  echo "include_poll_samples=$INCLUDE_POLL"
} >"$STAMP_DIR/backup-manifest.txt"
echo "Backup complete: $ARCHIVE"
echo "Stamp copy: $STAMP_DIR/workspace-full.tgz"
