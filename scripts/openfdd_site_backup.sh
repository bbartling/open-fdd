#!/usr/bin/env bash
# Back up an existing Open-FDD edge site without deleting workspace data.
#
# Typical:
#   cd ~/open-fdd
#   ./scripts/openfdd_site_backup.sh
#
# Fast backup without large BACnet poll CSV history:
#   BACKUP_INCLUDE_POLL_SAMPLES=0 ./scripts/openfdd_site_backup.sh
#
# Env:
#   BACKUP_ROOT                       Backup dir, default ~/openfdd-backups/latest
#   BACKUP_INCLUDE_POLL_SAMPLES=1     Include workspace/bacnet/polls, default 1
#   BACKUP_TIMEOUT_SECS=1800          Tar timeout
#   OPENFDD_ALLOW_SUDO=0              Do not auto-sudo by default
#   OPENFDD_PURGE_OLD_BACKUPS=0       Do not delete sibling backups by default
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=openfdd_site_lib.sh
source "$ROOT/scripts/openfdd_site_lib.sh"
cd "$ROOT"

BACKUP_ROOT="${BACKUP_ROOT:-$HOME/openfdd-backups/latest}"
BACKUP_INCLUDE_POLL_SAMPLES="${BACKUP_INCLUDE_POLL_SAMPLES:-1}"
BACKUP_TIMEOUT_SECS="${BACKUP_TIMEOUT_SECS:-1800}"
OPENFDD_ALLOW_SUDO="${OPENFDD_ALLOW_SUDO:-0}"
OPENFDD_PURGE_OLD_BACKUPS="${OPENFDD_PURGE_OLD_BACKUPS:-0}"

ARCHIVE="$(openfdd_backup_archive_path "$BACKUP_ROOT")"
ARCHIVE_TMP="${ARCHIVE}.partial"
MANIFEST="$(openfdd_backup_manifest_path "$BACKUP_ROOT")"
TAR_STDERR="$BACKUP_ROOT/tar.stderr"

cleanup_partial_archive() {
  rm -f "${ARCHIVE_TMP:-}" 2>/dev/null || true
}
trap cleanup_partial_archive EXIT

echo "=== Open-FDD site backup ==="
echo "Site root:  $ROOT"
echo "Backup dir: $BACKUP_ROOT"
echo "Poll CSVs:  $([[ "$BACKUP_INCLUDE_POLL_SAMPLES" == "1" ]] && echo included || echo skipped)"
echo ""

mkdir -p "$BACKUP_ROOT"
rm -f "$ARCHIVE_TMP" "$TAR_STDERR"

openfdd_warn_plaintext_passwords "$ROOT" || true
openfdd_report_root_owned_workspace_files "$ROOT" || true

echo ""
echo "Checking workspace readability..."
if ! openfdd_check_workspace_readable "$ROOT"; then
  if [[ "$OPENFDD_ALLOW_SUDO" == "1" ]]; then
    echo "WARN: OPENFDD_ALLOW_SUDO=1 set, but auto-sudo archive is intentionally disabled in this hardened script." >&2
    echo "      Fix ownership first, then rerun backup." >&2
  fi
  exit 1
fi

echo ""
echo "Workspace size before archive:"
du -sh workspace || true

echo ""
echo "Snapshot Docker/compose state"
cp -a "$ROOT/docker-compose.yml" "$BACKUP_ROOT/docker-compose.yml.snapshot" 2>/dev/null || true
cp -a "$ROOT/docker" "$BACKUP_ROOT/docker.snapshot" 2>/dev/null || true

docker compose config > "$BACKUP_ROOT/docker-compose-config-before.yml" 2>/dev/null || true
docker compose ps > "$BACKUP_ROOT/docker-compose-ps-before.txt" 2>/dev/null || true
docker ps > "$BACKUP_ROOT/docker-ps-before.txt" 2>/dev/null || true
docker compose config --images > "$BACKUP_ROOT/docker-images-before.txt" 2>/dev/null || true
docker volume ls > "$BACKUP_ROOT/docker-volumes-before.txt" 2>/dev/null || true

{
  echo "backup_started_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "backup_include_poll_samples=$BACKUP_INCLUDE_POLL_SAMPLES"
  echo "backup_tar_xattrs=0"
  echo "backup_timeout_secs=$BACKUP_TIMEOUT_SECS"
} > "$MANIFEST"

tar_args=(-C "$ROOT" -czf "$ARCHIVE_TMP" --warning=no-file-changed)
if [[ "$BACKUP_INCLUDE_POLL_SAMPLES" != "1" ]]; then
  tar_args+=(--exclude=workspace/bacnet/polls)
fi
tar_args+=(workspace)

echo ""
echo "Archiving workspace/…"
echo "This may take several minutes on historian sites."

set +e
if command -v pv >/dev/null 2>&1; then
  workspace_bytes="$(du -sb "$ROOT/workspace" 2>/dev/null | awk '{print $1}')"
  tar_stream_args=(-C "$ROOT" -cf -)
  if [[ "$BACKUP_INCLUDE_POLL_SAMPLES" != "1" ]]; then
    tar_stream_args+=(--exclude=workspace/bacnet/polls)
  fi
  tar_stream_args+=(workspace)

  timeout "$BACKUP_TIMEOUT_SECS" tar "${tar_stream_args[@]}" 2>"$TAR_STDERR" \
    | pv -s "${workspace_bytes:-0}" \
    | gzip -1 > "$ARCHIVE_TMP"
  rc=${PIPESTATUS[0]}
else
  timeout "$BACKUP_TIMEOUT_SECS" tar "${tar_args[@]}" 2>"$TAR_STDERR"
  rc=$?
fi
set -e

if [[ "$rc" != "0" ]]; then
  echo "" >&2
  echo "ERROR: backup tar failed with rc=$rc" >&2
  echo "Partial archive is not valid and will be removed: $ARCHIVE_TMP" >&2
  echo "See: $TAR_STDERR" >&2
  echo "" >&2
  echo "Common fix:" >&2
  echo '  cd ~/open-fdd' >&2
  echo '  sudo chown -R "$(id -u):$(id -g)" workspace' >&2
  echo '  sudo chmod -R u+rwX workspace' >&2
  echo "" >&2
  echo "No automatic sudo retry was attempted." >&2
  rm -f "$ARCHIVE_TMP"
  exit 1
fi

if ! tar -tzf "$ARCHIVE_TMP" workspace >/dev/null 2>&1; then
  echo "ERROR: partial archive failed integrity check: $ARCHIVE_TMP" >&2
  rm -f "$ARCHIVE_TMP"
  exit 1
fi

mv "$ARCHIVE_TMP" "$ARCHIVE"

{
  echo "backup_finished_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "archive_bytes=$(stat -c '%s' "$ARCHIVE" 2>/dev/null || echo 0)"
} >> "$MANIFEST"

if [[ "$OPENFDD_PURGE_OLD_BACKUPS" == "1" ]]; then
  echo ""
  echo "OPENFDD_PURGE_OLD_BACKUPS=1 set."
  echo "No automatic deletion implemented here; use a manual reviewed find command to remove old backups."
else
  echo ""
  echo "Backup retention cleanup skipped."
  echo "Keeping sibling backups such as keep-*."
fi

echo ""
echo "Backup saved to: $BACKUP_ROOT"
du -sh "$ARCHIVE" || true

echo ""
echo "Critical paths inside workspace/:"
echo "  workspace/data/feather_store/     historian"
echo "  workspace/data/*.json             model, rules, FDD results"
echo "  workspace/bacnet/commissioning/   BACnet bind, points.csv"
echo "  workspace/bacnet/polls/           poll samples.csv (optional in fast mode)"
echo "  workspace/auth.env.local          login secrets"
echo "  workspace/api/static/app/         dashboard bundle (if rsync'd)"

echo ""
echo "Next: ./scripts/openfdd_site_update.sh"
echo "  safe Docker prune, image pull, validate, optional backup purge"