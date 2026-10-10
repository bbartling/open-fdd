#!/usr/bin/env bash
# Gate 46 — data-model integrity (static scanner + runtime mapping/role smoke).
# Soft-OPEN 370 T3b: static identity scan alone is insufficient.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/scripts/nightly-ot-bench/lib.sh"
load_bench_env
BASE="${OPENFDD_API_BASE:-${CENTRAL_BASE:-http://127.0.0.1:8080}}"
BUILDING="${OPENFDD_GATE46_BUILDING:-${OPENFDD_BUILDING_ID:-${OPENFDD_SYNTH59_BUILDING:-OPENFDD_SYNTHETIC_59_RULE_WEEK_V1}}}"
ART="${ARTIFACT_DIR:-$ROOT/reports/gate46_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$ART"

python3 "$ROOT/scripts/qualification/no_equipment_id_heuristics.py" --root "$ROOT" \
  | tee "$ART/scanner.txt"

TOKEN=""
if [[ -n "${OPENFDD_ADMIN_PASSWORD:-}" ]]; then
  TOKEN=$(curl -sf --max-time 10 -X POST "$BASE/api/auth/login" \
    -H 'Content-Type: application/json' \
    -d "{\"username\":\"${OPENFDD_ADMIN_USER:-admin}\",\"password\":\"$OPENFDD_ADMIN_PASSWORD\"}" \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("token") or d.get("access_token") or "")' 2>/dev/null || true)
fi
if [[ -z "$TOKEN" ]]; then
  echo "BLOCKED: no auth for runtime mapping smoke" | tee "$ART/BLOCKED.txt"
  exit 2
fi

# Canonical package-mapping route (not /api/csv/package/mapping).
MAP_URL="$BASE/api/csv/import/package/mapping?building_id=${BUILDING}"
http_code=$(curl -sS -o "$ART/mapping.json" -w '%{http_code}' --max-time 30 \
  -H "Authorization: Bearer $TOKEN" "$MAP_URL" || echo 000)
echo "mapping_http=$http_code building=$BUILDING" | tee "$ART/mapping_meta.txt"
if [[ "$http_code" != "200" ]]; then
  echo "FAIL: mapping HTTP $http_code for building=$BUILDING" | tee "$ART/FAIL.txt"
  exit 1
fi

python3 - <<PY
import json, sys
from pathlib import Path
m = json.loads(Path("$ART/mapping.json").read_text())
if not isinstance(m, dict):
    print("FAIL: mapping not an object", file=sys.stderr)
    sys.exit(1)
# Owner-positive: mapping payload must expose equipment and role-ish structure.
equips = m.get("equipment") or m.get("equipment_ids") or m.get("equipments") or []
if isinstance(equips, dict):
    equips = list(equips.keys())
roles = m.get("roles") or m.get("role_map") or {}
# Empty {} / generic denial is not owner-positive runtime proof.
if not equips and not roles:
    print("FAIL: empty mapping without equipment/roles (not owner-positive)", file=sys.stderr)
    sys.exit(1)
print("PASS gate 46 scanner + runtime mapping smoke")
print(f"equipment_entries={len(equips) if hasattr(equips,'__len__') else 'n/a'} keys={list(m)[:12]}")
PY
echo "PASS gate 46" | tee "$ART/gate46.txt"
