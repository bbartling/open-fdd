#!/usr/bin/env bash
# Backup: workspace tarball + driver_tree/assignments JSON sidecars + image-tag manifest.
# Run before any stack image update or destructive change (rollback unit).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

WORKSPACE_PATH="${OPENFDD_WORKSPACE_PATH:-$ROOT/workspace}"
BACKUP_DIR="${OPENFDD_BACKUP_DIR:-$ROOT/backups}"
TS="$(date +%Y%m%d-%H%M%S)"
ARCHIVE="$BACKUP_DIR/pre-cutover-${TS}.tar.gz"
STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT

if [[ ! -d "$WORKSPACE_PATH" ]]; then
  echo "ERROR: workspace not found: $WORKSPACE_PATH" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"

echo "== Open-FDD pre-cutover backup =="
echo "workspace=$WORKSPACE_PATH"
echo "archive=$ARCHIVE"

# Primary workspace archive (exclude nested backup dirs to avoid recursion).
tar -czf "$ARCHIVE" \
  --exclude='backups' \
  --exclude='*.tar.gz' \
  --exclude='*.tgz' \
  -C "$(dirname "$WORKSPACE_PATH")" \
  "$(basename "$WORKSPACE_PATH")"

# Sidecar copies of migration-critical JSON when present under workspace/data.
DATA_ROOT="$WORKSPACE_PATH/data"
SIDEcar_DIR="$STAGING/migration-sidecars"
mkdir -p "$SIDEcar_DIR"

copy_if_present() {
  local rel="$1"
  local src="$DATA_ROOT/$rel"
  if [[ -f "$src" ]]; then
    local dest_dir="$SIDEcar_DIR/$(dirname "$rel")"
    mkdir -p "$dest_dir"
    cp -a "$src" "$dest_dir/"
    echo "sidecar: data/$rel"
  fi
}

copy_if_present "drivers/bacnet/driver_tree.json"
copy_if_present "model/assignments.json"
copy_if_present "drivers/bacnet/overrides.json"
copy_if_present "drivers/modbus/driver_tree.json"
copy_if_present "drivers/haystack/driver_tree.json"

if [[ -n "$(find "$SIDEcar_DIR" -type f 2>/dev/null | head -1)" ]]; then
  SIDEcar_ARCHIVE="$BACKUP_DIR/pre-cutover-${TS}-migration-sidecars.tar.gz"
  tar -czf "$SIDEcar_ARCHIVE" -C "$STAGING" migration-sidecars
  echo "sidecar archive: $SIDEcar_ARCHIVE"
fi

# Record image tags in use for rollback (env overrides + compose defaults).
MANIFEST="$BACKUP_DIR/pre-cutover-${TS}-image-tags.env"
{
  echo "# captured $(date -Iseconds) — restore these for rollback"
  echo "OPENFDD_CENTRAL_IMAGE=${OPENFDD_CENTRAL_IMAGE:-ghcr.io/bbartling/openfdd-central:nightly}"
  echo "OPENFDD_UI_IMAGE=${OPENFDD_UI_IMAGE:-ghcr.io/bbartling/openfdd-ui:nightly}"
  echo "OPENFDD_FIELDBUS_IMAGE=${OPENFDD_FIELDBUS_IMAGE:-ghcr.io/bbartling/openfdd-fieldbus:nightly}"
  echo "OPENFDD_MQTT_IMAGE=${OPENFDD_MQTT_IMAGE:-ghcr.io/bbartling/openfdd-mqtt:nightly}"
  echo "OPENFDD_MCP_IMAGE=${OPENFDD_MCP_IMAGE:-ghcr.io/bbartling/openfdd-mcp:nightly}"
} >"$MANIFEST"
echo "image tag manifest: $MANIFEST"

echo ""
echo "Backup complete: $ARCHIVE"
echo ""
echo "=== Rollback instructions ==="
echo "1. Stop the new central+fieldbus stack:"
echo "     docker compose -f docker/compose.standalone.yml down"
echo "     docker compose -f docker/compose.central.yml down"
echo "     docker compose -f docker/compose.edge.yml down"
echo "2. Restore workspace:"
echo "     tar -xzf \"$ARCHIVE\" -C \"$(dirname "$WORKSPACE_PATH")\""
echo "3. Pin images from $MANIFEST (or your pre-cutover sha-* tags):"
echo "     source \"$MANIFEST\""
echo "4. Restart the previous stack with those image env vars."
echo "5. Retain pre-cutover GHCR tags (sha-<git-sha>) as the immutable rollback unit."
echo "   See docker/VERSION_MANIFEST.md and docs/central-fieldbus-cutover.md."
