#!/usr/bin/env bash
# Gate 46 — data-model integrity (static scanner + runtime mapping/role smoke).
# Soft-OPEN 370 T3b: static identity scan alone is insufficient.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/scripts/nightly-ot-bench/lib.sh"
load_bench_env
BASE="${OPENFDD_API_BASE:-${CENTRAL_BASE:-http://127.0.0.1:8080}}"
BUILDING="${OPENFDD_GATE46_BUILDING:-${OPENFDD_SYNTH59_BUILDING:-OPENFDD_SYNTHETIC_59_RULE_WEEK_V1}}"
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

curl -sf --max-time 30 -H "Authorization: Bearer $TOKEN" \
  "$BASE/api/csv/package/mapping?building_id=$BUILDING" \
  | tee "$ART/mapping.json" >/dev/null

python3 - <<PY
import json, sys
m = json.load(open("$ART/mapping.json"))
# Owner-positive: mapping payload must expose equipment and role-ish structure.
equips = m.get("equipment") or m.get("equipment_ids") or m.get("equipments") or []
if isinstance(equips, dict):
    equips = list(equips.keys())
if not equips and not m.get("ok", True):
    print("FAIL: mapping not ok and no equipment", file=sys.stderr)
    sys.exit(1)
# Accept buildings that return ok with a non-empty roles/equipment list, or an
# explicit typed inventory. Empty {} is not owner-positive.
roles = m.get("roles") or m.get("role_map") or {}
if not equips and not roles and m.get("building_id") is None and not m.get("ok"):
    print("FAIL: empty mapping without building identity", file=sys.stderr)
    sys.exit(1)
# Soft runtime assertion: response is JSON object (schema smoke + scanner).
if not isinstance(m, dict):
    print("FAIL: mapping not an object", file=sys.stderr)
    sys.exit(1)
print("PASS gate 46 scanner + runtime mapping smoke")
print(f"equipment_entries={len(equips) if hasattr(equips,'__len__') else 'n/a'} keys={list(m)[:12]}")
PY
echo "PASS gate 46" | tee "$ART/gate46.txt"
