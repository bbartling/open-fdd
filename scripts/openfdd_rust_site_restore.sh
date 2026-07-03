#!/usr/bin/env bash
# Restore workspace historian (Arrow/Feather/JSONL) from staging dir or workspace-full.tgz backup.
#
#   ./scripts/openfdd_rust_site_restore.sh --from-staging workspace/backups/historian-staging/pre-update
#   ./scripts/openfdd_rust_site_restore.sh --from-backup ~/openfdd-backups/latest/workspace-full.tgz
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_rust_site_lib.sh
source "$ROOT/scripts/openfdd_rust_site_lib.sh"

FROM_STAGING=""
FROM_BACKUP=""
DRY_RUN="${DRY_RUN:-0}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --from-staging) FROM_STAGING="$2"; shift 2 ;;
    --from-backup) FROM_BACKUP="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

[[ -n "$FROM_STAGING" || -n "$FROM_BACKUP" ]] || {
  echo "Usage: $0 --from-staging DIR | --from-backup ARCHIVE.tgz" >&2
  exit 1
}

if [[ "$DRY_RUN" == "1" ]]; then
  echo "DRY_RUN restore staging=$FROM_STAGING backup=$FROM_BACKUP"
  exit 0
fi

if [[ -n "$FROM_STAGING" ]]; then
  "$ROOT/scripts/openfdd_rust_historian_staging.sh" restore "$FROM_STAGING"
  exit $?
fi

[[ -f "$FROM_BACKUP" ]] || { echo "ERROR: backup not found: $FROM_BACKUP" >&2; exit 1; }
openfdd_rust_validate_backup_archive "$FROM_BACKUP"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
tar -xzf "$FROM_BACKUP" -C "$TMP" workspace/data/historian 2>/dev/null || \
  tar -xzf "$FROM_BACKUP" -C "$TMP" workspace 2>/dev/null || true

STAGE="$TMP/restore-staging"
mkdir -p "$STAGE"
if [[ -d "$TMP/workspace/data/historian" ]]; then
  cp -a "$TMP/workspace/data/historian" "$STAGE/"
elif [[ -d "$TMP/workspace/data" ]]; then
  cp -a "$TMP/workspace/data" "$STAGE/"
fi

"$ROOT/scripts/openfdd_rust_historian_staging.sh" restore "$STAGE"
echo "Restore from backup OK: $FROM_BACKUP"
