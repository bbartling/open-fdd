#!/usr/bin/env bash
# One-shot "update safely, keep data, resume" wrapper for Open-FDD compose recipes.
#
# Flow:
# - Snapshot current OPENFDD_IMAGE_TAG and GHCR digests
# - (Optional) run non-aggressive docker maintenance prune
# - Pull+recreate via openfdd_stack_up.sh
# - If health fails, rollback to previous digests and restart
#
# Usage:
#   ./scripts/openfdd_maint_update_resume.sh [standalone|central|edge|csv|react|react-ot] [OPENFDD_IMAGE_TAG]
#   ./scripts/openfdd_maint_update_resume.sh react-ot nightly
#
# Options:
#   --skip-maintenance
#   --no-backup
#   --backup-dir /path
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

RECIPE="${1:-react-ot}"
NEW_TAG="${2:-${OPENFDD_IMAGE_TAG:-nightly}}"

DO_MAINT=1
DO_BACKUP=1
BACKUP_DIR="${OPENFDD_BACKUP_DIR:-}"
DO_CLEANUP_AFTER_OK=0

shift 2 || true
while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-maintenance) DO_MAINT=0; shift ;;
    --no-backup) DO_BACKUP=0; shift ;;
    --cleanup-after-ok) DO_CLEANUP_AFTER_OK=1; shift ;;
    --backup-dir) BACKUP_DIR="$2"; shift 2 ;;
    -h|--help)
      cat <<EOF
Usage: $0 [standalone|central|edge|csv|react|react-ot] [OPENFDD_IMAGE_TAG]

Example:
  $0 react-ot nightly

Options:
  --skip-maintenance   Skip docker prune step
  --no-backup          Skip snapshot/backup directory
  --cleanup-after-ok  Delete this run's snapshot directory if update succeeds
  --backup-dir DIR    Where to write backup snapshots
EOF
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "${RECIPE}" ]]; then
  echo "ERROR: missing recipe" >&2
  exit 2
fi

OLD_TAG="${OPENFDD_IMAGE_TAG:-nightly}"

default_backup_root="$ROOT/.backups"
if [[ -z "$BACKUP_DIR" ]]; then
  BACKUP_DIR="$default_backup_root"
fi
mkdir -p "$BACKUP_DIR"

TS="$(date +%Y%m%d_%H%M%S)"
SNAP_DIR="$BACKUP_DIR/openfdd_maint_update_resume_${RECIPE}_${TS}"

log() { echo "==> $*"; }
warn() { echo "WARN: $*" >&2; }

redacted_copy_env() {
  local src="$1"
  local dst="$2"
  if [[ ! -f "$src" ]]; then
    return 0
  fi
  mkdir -p "$(dirname "$dst")"
  # Redact known secrets; keep everything else intact.
  awk -F= '
    {
      key=$1
      if (key ~ /(JWT_SECRET|ADMIN_PASSWORD|OPENWEATHER_API_KEY|HAYSTACK_PASSWORD|PASSWORD|TOKEN)/) {
        print key "=<redacted>"
      } else {
        print $0
      }
    }
  ' "$src" > "$dst"
}

manifest_digest() {
  # Print the OCI config digest for the single-platform manifest.
  # Returns empty string on failure.
  local ref="$1"
  docker manifest inspect "$ref" 2>/dev/null | python3 -c '
import json,sys
data=json.load(sys.stdin)
if isinstance(data, list) and data:
    d=data[0].get("Descriptor",{})
    print(d.get("digest",""))
else:
    print("")
' 2>/dev/null || true
}

snapshot() {
  mkdir -p "$SNAP_DIR"
  log "Snapshot: $SNAP_DIR"

  # Save redacted env snapshots.
  redacted_copy_env "$ROOT/.env" "$SNAP_DIR/.env"
  if [[ -f "$ROOT/workspace/.env" ]]; then
    redacted_copy_env "$ROOT/workspace/.env" "$SNAP_DIR/workspace.env"
  fi

  # Save container/image state (non-sensitive).
  docker ps --format '{{.Names}} {{.Image}} {{.Status}}' > "$SNAP_DIR/docker_ps.txt" 2>/dev/null || true

  # Save old tag + GHCR digests (for rollback pins).
  local tags=(central web fieldbus mqtt mcp)
  {
    echo "{"
    echo "  \"recipe\": \"$RECIPE\","
    echo "  \"old_tag\": \"$OLD_TAG\","
    echo "  \"new_tag\": \"$NEW_TAG\","
    echo "  \"digests\": {"
    local first=1
    for name in "${tags[@]}"; do
      ref="ghcr.io/bbartling/openfdd-${name}:${OLD_TAG}"
      digest="$(manifest_digest "$ref")"
      if [[ $first -eq 0 ]]; then echo ","; fi
      first=0
      echo -n "    \"${name}\": "
      if [[ -n "$digest" ]]; then
        echo -n "\"$digest\""
      else
        echo -n "\"\""
      fi
    done
    echo
    echo "  }"
    echo "}"
  } > "$SNAP_DIR/state.json"

  log "Snapshot complete"
}

rollback() {
  local state_file="$SNAP_DIR/state.json"
  if [[ ! -f "$state_file" ]]; then
    warn "No snapshot state.json; cannot rollback reliably."
    return 1
  fi

  log "Rollback: restore previous digests and restart"

  # Extract digests with Python (no jq dependency).
  python3 - "$state_file" "$OLD_TAG" <<'PY'
import json,sys
state_file=sys.argv[1]
old_tag=sys.argv[2]
with open(state_file,'r') as f:
    s=json.load(f)
dig=s.get("digests",{}) or {}
mapping={
  "central":"OPENFDD_CENTRAL_IMAGE",
  "web":"OPENFDD_WEB_IMAGE",
  "fieldbus":"OPENFDD_FIELDBUS_IMAGE",
  "mqtt":"OPENFDD_MQTT_IMAGE",
  "mcp":"OPENFDD_MCP_IMAGE",
}
for key, env_name in mapping.items():
    digest=dig.get(key,"")
    if digest:
        print(f'{env_name}="ghcr.io/bbartling/openfdd-{key}@{digest}"')
PY

  # shellcheck disable=SC2046
  eval "$(
    python3 - "$SNAP_DIR/state.json" <<'PY'
import json,sys
with open(sys.argv[1],'r') as f:
    s=json.load(f)
dig=s.get("digests",{}) or {}
mapping={
  "central":"OPENFDD_CENTRAL_IMAGE",
  "web":"OPENFDD_WEB_IMAGE",
  "fieldbus":"OPENFDD_FIELDBUS_IMAGE",
  "mqtt":"OPENFDD_MQTT_IMAGE",
  "mcp":"OPENFDD_MCP_IMAGE",
}
for key, env_name in mapping.items():
    digest=dig.get(key,"")
    if digest:
        print(f'{env_name}="ghcr.io/bbartling/openfdd-{key}@{digest}"')
PY
  )"

  export OPENFDD_IMAGE_TAG="$OLD_TAG"

  # Recreate using pinned image digests; avoid pulling again.
  "$ROOT/scripts/openfdd_stack_up.sh" "$RECIPE" --no-pull
}

main() {
  if [[ "$DO_BACKUP" -eq 1 ]]; then
    snapshot
  else
    log "Skipping backup"
  fi

  if [[ "$DO_MAINT" -eq 1 ]]; then
    log "Running docker maintenance (non-aggressive prune)"
    "$ROOT/scripts/openfdd_docker_maintenance.sh"
  else
    log "Skipping docker maintenance"
  fi

  log "Update: recipe=$RECIPE old_tag=$OLD_TAG new_tag=$NEW_TAG"
  export OPENFDD_IMAGE_TAG="$NEW_TAG"

  if "$ROOT/scripts/openfdd_stack_up.sh" "$RECIPE"; then
    log "Update OK: recipe=$RECIPE tag=$NEW_TAG"
    if [[ "$DO_BACKUP" -eq 1 && "$DO_CLEANUP_AFTER_OK" -eq 1 && -d "$SNAP_DIR" ]]; then
      log "Cleanup: removing snapshot dir $SNAP_DIR"
      rm -rf "$SNAP_DIR"
    fi
    echo "Backup snapshot: $SNAP_DIR"
    return 0
  fi

  warn "Update failed; attempting rollback"
  if rollback; then
    log "Rollback OK"
    echo "Backup snapshot: $SNAP_DIR"
    return 0
  fi

  warn "Rollback failed; stack may be unhealthy."
  echo "Backup snapshot: $SNAP_DIR"
  return 1
}

main "$@"

