#!/usr/bin/env bash
# Backup Open-FDD site state before image upgrades (run on the edge host).
#
#   cd ~/open-fdd
#   ./scripts/openfdd_site_backup.sh
#   BACKUP_ROOT=~/openfdd-backups/latest ./scripts/openfdd_site_backup.sh
#
# Default overwrites ~/openfdd-backups/latest (rigorous testing — no timestamp archive pile-up).
# Timestamped dir only when BACKUP_ROOT is set explicitly.
#
# Fast pre-upgrade backup (skips large poll CSV history; feather/model/rules kept):
#   BACKUP_INCLUDE_POLL_SAMPLES=0 ./scripts/openfdd_site_backup.sh
#
# Backs up: workspace/ (feather, BACnet CSVs, model, auth env, logs), compose files, docker state.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

BACKUP_ROOT="${BACKUP_ROOT:-$HOME/openfdd-backups/latest}"
BACKUP_INCLUDE_POLL_SAMPLES="${BACKUP_INCLUDE_POLL_SAMPLES:-1}"
BACKUP_TIMEOUT_SECS="${BACKUP_TIMEOUT_SECS:-1800}"
BACKUP_TAR_XATTRS="${BACKUP_TAR_XATTRS:-0}"
# Overwrite prior backup at this path (rigorous testing pace — one rolling copy).
rm -rf "$BACKUP_ROOT"
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
echo "Poll CSVs:  $([[ "$BACKUP_INCLUDE_POLL_SAMPLES" == "1" ]] && echo included || echo excluded \(fast mode\))"
echo ""

if [[ -f "$ROOT/scripts/fix_edge_workspace_permissions.sh" ]]; then
  COMPOSE_FILE="$COMPOSE_FILE" "$ROOT/scripts/fix_edge_workspace_permissions.sh" || true
fi

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

echo "Workspace size before archive:"
du -sh workspace workspace/data/feather_store workspace/bacnet/polls 2>/dev/null || du -sh workspace

ARCHIVE="$BACKUP_ROOT/workspace-full.tgz"
MANIFEST="$BACKUP_ROOT/backup-manifest.txt"
{
  echo "backup_started_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "backup_include_poll_samples=${BACKUP_INCLUDE_POLL_SAMPLES}"
  echo "backup_tar_xattrs=${BACKUP_TAR_XATTRS}"
  echo "backup_timeout_secs=${BACKUP_TIMEOUT_SECS}"
} >"$MANIFEST"

TAR_OPTS=(-czf "$ARCHIVE" --warning=no-file-changed)
if [[ "$BACKUP_TAR_XATTRS" == "1" ]]; then
  TAR_OPTS=(--xattrs --acls "${TAR_OPTS[@]}")
fi
if [[ "$BACKUP_INCLUDE_POLL_SAMPLES" != "1" ]]; then
  TAR_OPTS+=(--exclude='workspace/bacnet/polls')
fi

echo "Archiving workspace/…"
set +e
if command -v timeout >/dev/null 2>&1; then
  timeout "${BACKUP_TIMEOUT_SECS}" tar "${TAR_OPTS[@]}" workspace 2>"$BACKUP_ROOT/tar.stderr"
else
  tar "${TAR_OPTS[@]}" workspace 2>"$BACKUP_ROOT/tar.stderr"
fi
rc=$?
set -e

if [[ "$rc" -eq 124 ]]; then
  echo "ERROR: tar timed out after ${BACKUP_TIMEOUT_SECS}s — retry with BACKUP_INCLUDE_POLL_SAMPLES=0" >&2
  exit 124
fi

if [[ "$rc" -ne 0 ]]; then
  echo "WARN: user tar failed (rc=${rc}); retrying with sudo (see $BACKUP_ROOT/tar.stderr)" >&2
  set +e
  if command -v timeout >/dev/null 2>&1; then
    timeout "${BACKUP_TIMEOUT_SECS}" sudo tar "${TAR_OPTS[@]}" workspace 2>>"$BACKUP_ROOT/tar.stderr"
    rc=$?
    sudo chown "$USER:$USER" "$ARCHIVE"
  else
    sudo tar "${TAR_OPTS[@]}" workspace 2>>"$BACKUP_ROOT/tar.stderr"
    rc=$?
    sudo chown "$USER:$USER" "$ARCHIVE"
  fi
  set -e
  if [[ "$rc" -eq 124 ]]; then
    echo "ERROR: sudo tar timed out after ${BACKUP_TIMEOUT_SECS}s — use BACKUP_INCLUDE_POLL_SAMPLES=0" >&2
    exit 124
  fi
  if [[ "$rc" -ne 0 ]]; then
    echo "ERROR: backup archive failed (rc=${rc})" >&2
    exit "$rc"
  fi
fi

if ! tar -tzf "$ARCHIVE" >/dev/null 2>&1; then
  echo "ERROR: archive failed integrity check: $ARCHIVE" >&2
  exit 1
fi

{
  echo "backup_finished_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "archive_bytes=$(stat -c '%s' "$ARCHIVE" 2>/dev/null || wc -c <"$ARCHIVE")"
} >>"$MANIFEST"

echo ""
echo "Backup saved to: $BACKUP_ROOT"
du -h "$ARCHIVE"
echo ""
echo "Critical paths inside workspace/:"
echo "  workspace/data/feather_store/     historian"
echo "  workspace/data/*.json             model, rules, FDD results"
echo "  workspace/bacnet/commissioning/   BACnet bind, points.csv"
echo "  workspace/bacnet/polls/           poll samples.csv (optional in fast mode)"
echo "  workspace/auth.env.local          login secrets"
echo "  workspace/api/static/app/         dashboard bundle (if rsync'd)"

# Drop legacy timestamped dirs — keep only the rolling latest backup.
legacy_root="$(dirname "$BACKUP_ROOT")"
if [[ -d "$legacy_root" && "$(basename "$BACKUP_ROOT")" == "latest" ]]; then
  for old in "$legacy_root"/*/; do
    [[ -d "$old" ]] || continue
    [[ "$old" == "${BACKUP_ROOT}/" ]] && continue
    rm -rf "$old"
  done
fi
