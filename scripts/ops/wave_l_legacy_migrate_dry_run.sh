#!/usr/bin/env bash
# Wave L L7 — legacy-tenant migrate dry-run (inventory only; never mutates volumes).
#
# Default: print planned assignment of existing buildings/edges ? tenant `legacy`.
# APPLY=1 is refused on Railway HTTPS hubs (no silent live migrate).
#
# Usage:
#   OPENFDD_API_BASE=https://… OPENFDD_ADMIN_PASSWORD=… \
#     ./scripts/ops/wave_l_legacy_migrate_dry_run.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Reuse nightly auth helpers when present.
if [[ -f "$ROOT/scripts/nightly-ot-bench/lib.sh" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT/scripts/nightly-ot-bench/lib.sh"
  load_bench_env
  cd "$ROOT"
  central_auth_setup
else
  CENTRAL_BASE="${OPENFDD_API_BASE:-${CENTRAL_BASE:-http://127.0.0.1:8080}}"
  CENTRAL_AUTH_HDR=()
fi

ART="${ARTIFACT_DIR:-$ROOT/reports/wave_l_legacy_migrate_dry_run_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$ART"
LOG="$ART/legacy_migrate_dry_run.log"
: >"$LOG"

if [[ "${APPLY:-0}" == "1" ]]; then
  case "${CENTRAL_BASE}" in
    https://*)
      echo "REFUSED: APPLY=1 on Railway HTTPS hub — operator live migrate is out of Wave L auto path" | tee -a "$LOG"
      exit 2
      ;;
  esac
  echo "REFUSED: APPLY=1 not implemented in Wave L (dry-run only; Stage C / operator runbook)" | tee -a "$LOG"
  exit 2
fi

health="$(curl -sS --max-time 30 "${CENTRAL_AUTH_HDR[@]+"${CENTRAL_AUTH_HDR[@]}"}" \
  "$CENTRAL_BASE/api/health")"
echo "$health" | tee "$ART/health.json" >/dev/null
mt="$(echo "$health" | jq -r '.multi_tenant // false')"
ver="$(echo "$health" | jq -r '.version // empty')"

tenants="$(curl -sS --max-time 30 "${CENTRAL_AUTH_HDR[@]+"${CENTRAL_AUTH_HDR[@]}"}" \
  "$CENTRAL_BASE/api/tenants")"
echo "$tenants" | tee "$ART/tenants.json" >/dev/null

buildings="$(curl -sS --max-time 60 "${CENTRAL_AUTH_HDR[@]+"${CENTRAL_AUTH_HDR[@]}"}" \
  "$CENTRAL_BASE/api/csv/import/package/buildings")"
echo "$buildings" | tee "$ART/package_buildings.json" >/dev/null

edges="$(curl -sS --max-time 30 "${CENTRAL_AUTH_HDR[@]+"${CENTRAL_AUTH_HDR[@]}"}" \
  "$CENTRAL_BASE/api/edges")"
echo "$edges" | tee "$ART/edges.json" >/dev/null

python3 - <<PY | tee "$ART/migrate_plan.json" | tee -a "$LOG"
import json, os
from pathlib import Path
art = Path("$ART")
health = json.loads((art / "health.json").read_text())
tenants = json.loads((art / "tenants.json").read_text())
buildings = json.loads((art / "package_buildings.json").read_text())
edges = json.loads((art / "edges.json").read_text())
bldg_ids = list(buildings.get("buildings") or [])
edge_sites = sorted({e.get("site_id") for e in (edges.get("edges") or []) if e.get("site_id")})
plan = {
    "ok": True,
    "mode": "dry_run",
    "apply": False,
    "multi_tenant": bool(health.get("multi_tenant")),
    "version": health.get("version"),
    "target_tenant_id": "legacy",
    "historian_prefix_when_off": "",
    "actions": [
        "Inventory package buildings + MQTT edge sites",
        "Assign all existing buildings to control-plane tenant 'legacy' (no Parquet delete)",
        "Keep OPENFDD_MULTI_TENANT=false until operator checklist signed",
        "Rollback = Wave K sha-9c3e8b1 / 3.4.0 + flag OFF",
    ],
    "package_buildings": bldg_ids,
    "mqtt_sites": edge_sites,
    "planned_building_ids": sorted(set(bldg_ids) | set(edge_sites)),
    "control_plane_tenants": tenants.get("tenants"),
    "writes": False,
    "note": "Dry-run only. See docs/operations/WAVE_L_LEGACY_MIGRATE_CHECKLIST.md",
}
print(json.dumps(plan, indent=2))
if plan["multi_tenant"]:
    raise SystemExit("multi_tenant must be false for Wave L dry-run on field hub")
if not any(t.get("id") == "legacy" for t in (tenants.get("tenants") or [])):
    raise SystemExit("legacy tenant missing from /api/tenants")
PY

echo "PASS Wave L legacy migrate dry-run (no writes) ART=$ART" | tee -a "$LOG"
exit 0
