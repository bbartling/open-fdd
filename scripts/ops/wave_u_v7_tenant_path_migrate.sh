#!/usr/bin/env bash
# Wave U V7 — additive hub-root → tenants/{tid}/ Parquet migrate (copy, never delete).
#
# Hard gate: run Railway workspace backup before APPLY on a live hub.
# Default is dry-run inventory only. APPLY=1 copies building trees; hub-root stays.
#
# Default map (control-plane ids from Wave N disposable / hub fixtures):
#   ACME         → tenants/acme/
#   BUILDING_100 → tenants/building_100/
#   LAKESIDE_ES  → tenants/lakeside_sd/
#
# Usage:
#   HUB_PARQUET_ROOT=/path/to/parquet ./scripts/ops/wave_u_v7_tenant_path_migrate.sh
#   APPLY=1 CONFIRM_BACKUP=1 HUB_PARQUET_ROOT=… ./scripts/ops/wave_u_v7_tenant_path_migrate.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

ART="${ARTIFACT_DIR:-$ROOT/reports/wave_u_v7_tenant_path_migrate_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$ART"
LOG="$ART/migrate.log"
: >"$LOG"
log() { echo "$*" | tee -a "$LOG"; }

HUB="${HUB_PARQUET_ROOT:-${OPENFDD_PARQUET_ROOT:-}}"
if [[ -z "$HUB" ]]; then
  if [[ -n "${OPENFDD_STORAGE_URL:-}" && "$OPENFDD_STORAGE_URL" == file://* ]]; then
    HUB="${OPENFDD_STORAGE_URL#file://}"
  elif [[ -d "$ROOT/workspace/openfdd" ]]; then
    HUB="$ROOT/workspace/openfdd"
  elif [[ -d "$ROOT/workspace/.cache/parquet" ]]; then
    HUB="$ROOT/workspace/.cache/parquet"
  else
    HUB="$ROOT/.cache/parquet"
  fi
fi

export HUB_PATH="$HUB"
export APPLY="${APPLY:-0}"
log "hub_parquet_root=$HUB"
log "artifact_dir=$ART apply=$APPLY"

python3 - <<'PY' | tee "$ART/inventory.json" | tee -a "$LOG"
import json, os
from pathlib import Path

hub = Path(os.environ["HUB_PATH"])
rows = [
    ("ACME", "acme"),
    ("BUILDING_100", "building_100"),
    ("LAKESIDE_ES", "lakeside_sd"),
]

def has_building(root: Path, bid: str) -> bool:
    legacy = root / f"building={bid}"
    canonical = root / "history" / f"building_id={bid}"
    return legacy.is_dir() or canonical.is_dir()

items = []
for bid, tid in rows:
    hub_hit = has_building(hub, bid)
    tenant_root = hub / "tenants" / tid
    tenant_hit = has_building(tenant_root, bid)
    if tenant_hit and hub_hit:
        action = "skip_already_migrated"
    elif tenant_hit:
        action = "skip_tenant_only"
    elif hub_hit:
        action = "copy_hub_to_tenant"
    else:
        action = "missing_both"
    items.append({
        "building_id": bid,
        "tenant_id": tid,
        "hub_present": hub_hit,
        "tenant_present": tenant_hit,
        "hub_legacy": str(hub / f"building={bid}"),
        "hub_canonical": str(hub / "history" / f"building_id={bid}"),
        "tenant_root": str(tenant_root),
        "action": action,
    })

report = {
    "ok": True,
    "mode": "apply" if os.environ.get("APPLY") == "1" else "dry_run",
    "hub_parquet_root": str(hub),
    "writes": os.environ.get("APPLY") == "1",
    "copy_not_delete": True,
    "items": items,
    "note": "Additive only. Hub-root building=* retained for dual-read fallback.",
}
print(json.dumps(report, indent=2))
PY

if [[ "${APPLY}" != "1" ]]; then
  log "PASS dry-run inventory only (set APPLY=1 to copy). ART=$ART"
  exit 0
fi

case "$HUB" in
  */reports/*|*/tmp/*|/tmp/*)
    log "APPLY on disposable path — backup confirm not required"
    ;;
  *)
    if [[ "${CONFIRM_BACKUP:-0}" != "1" ]]; then
      log "REFUSED: APPLY=1 requires CONFIRM_BACKUP=1 after ./scripts/railway_central_workspace_backup.sh"
      exit 2
    fi
    ;;
esac

copy_tree() {
  local src="$1" dest="$2"
  if [[ ! -e "$src" ]]; then
    return 0
  fi
  mkdir -p "$dest"
  if command -v rsync >/dev/null 2>&1; then
    rsync -a "$src"/ "$dest"/
  else
    cp -a "$src"/. "$dest"/
  fi
}

for row in "ACME|acme" "BUILDING_100|building_100" "LAKESIDE_ES|lakeside_sd"; do
  bid="${row%%|*}"
  tid="${row##*|}"
  tenant_root="$HUB/tenants/$tid"
  mkdir -p "$tenant_root"
  if [[ -d "$HUB/building=${bid}" ]]; then
    copy_tree "$HUB/building=${bid}" "$tenant_root/building=${bid}"
    log "COPIED building=${bid} -> tenants/${tid}/building=${bid}"
  fi
  if [[ -d "$HUB/history/building_id=${bid}" ]]; then
    mkdir -p "$tenant_root/history"
    copy_tree "$HUB/history/building_id=${bid}" "$tenant_root/history/building_id=${bid}"
    log "COPIED history/building_id=${bid} -> tenants/${tid}/history/building_id=${bid}"
  fi
done

python3 - <<'PY' | tee "$ART/apply_result.json" | tee -a "$LOG"
import json, os, sys
from pathlib import Path

hub = Path(os.environ["HUB_PATH"])
rows = [("ACME", "acme"), ("BUILDING_100", "building_100"), ("LAKESIDE_ES", "lakeside_sd")]

def has_building(root: Path, bid: str) -> bool:
    return (root / f"building={bid}").is_dir() or (root / "history" / f"building_id={bid}").is_dir()

out = []
ok = True
for bid, tid in rows:
    tenant_root = hub / "tenants" / tid
    hub_hit = has_building(hub, bid)
    tenant_hit = has_building(tenant_root, bid)
    if hub_hit and not tenant_hit:
        ok = False
    out.append({
        "building_id": bid,
        "tenant_id": tid,
        "hub_still_present": hub_hit,
        "tenant_present": tenant_hit,
    })
print(json.dumps({"ok": ok, "copy_not_delete": True, "items": out}, indent=2))
sys.exit(0 if ok else 1)
PY

log "PASS Wave U V7 additive tenant path migrate ART=$ART"
exit 0
