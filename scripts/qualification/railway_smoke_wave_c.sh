#!/usr/bin/env bash
# Wave C Railway smoke — hub health + fieldbus + edges telemetry + Overview markers.
# Not a full matrix. Never restores/writes OT. Requires railway CLI + admin password var.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

BASE="${OPENFDD_API_BASE:-https://openfdd-web-production-af99.up.railway.app}"
ART="${ARTIFACT_DIR:-$ROOT/reports/waveC_railway_smoke_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$ART"

if [[ -z "${OPENFDD_ADMIN_PASSWORD:-}" ]]; then
  OPENFDD_ADMIN_PASSWORD="$(railway variables --service openfdd-central-cQ-F --json | jq -r '.OPENFDD_ADMIN_PASSWORD')"
fi
export OPENFDD_ADMIN_PASSWORD

TOK="$(curl -sf --max-time 20 -X POST "$BASE/api/auth/login" \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg p "$OPENFDD_ADMIN_PASSWORD" '{username:"admin",password:$p}')" \
  | jq -r '.token // .access_token // empty')"
[[ -n "$TOK" ]]

curl -sf --max-time 20 "$BASE/api/health" | tee "$ART/health.json" >/dev/null
curl -sf --max-time 20 -H "Authorization: Bearer $TOK" "$BASE/api/edges" | tee "$ART/edges.json" >/dev/null
curl -sf --max-time 90 -X POST "$BASE/api/analytics/sensor-stats" \
  -H "Authorization: Bearer $TOK" -H 'Content-Type: application/json' \
  -d '{"building_id":"bldg2"}' | tee "$ART/sensor-stats-bldg2.json" >/dev/null
curl -sf --max-time 90 -X POST "$BASE/api/analytics/zone-other-health" \
  -H "Authorization: Bearer $TOK" -H 'Content-Type: application/json' \
  -d '{"building_id":"bldg2"}' | tee "$ART/zone-other-bldg2.json" >/dev/null
curl -sf --max-time 5 http://127.0.0.1:8081/health | tee "$ART/fieldbus_health.json" >/dev/null \
  || echo '{"ok":false,"note":"local fieldbus :8081 unreachable"}' | tee "$ART/fieldbus_health.json" >/dev/null

python3 - "$ART" <<'PY'
import json, sys
from pathlib import Path
art = Path(sys.argv[1])
health = json.loads((art / "health.json").read_text())
edges = json.loads((art / "edges.json").read_text())
stats = json.loads((art / "sensor-stats-bldg2.json").read_text())
zone = json.loads((art / "zone-other-bldg2.json").read_text())
fb = json.loads((art / "fieldbus_health.json").read_text())
telem = [e for e in edges.get("edges", []) if e.get("has_telemetry")]
rows = (stats.get("analytics") or {}).get("rows") or []
roles = [r.get("role") for r in rows]
equips = [r.get("equipment_id") for r in rows]
blob = json.dumps(stats) + json.dumps(zone)
# Cookbook maps zone-air-temp → zone_t; accept either marker.
has_zone = ("zone_t" in roles) or ("zone-air-temp" in roles) or ("zone_t" in blob)
has_loop = "bldg2-zone-loopback" in equips or "bldg2-zone-loopback" in blob
zone_rows = len((zone.get("analytics") or {}).get("rows") or [])
ok = bool(telem) and has_zone and has_loop and zone_rows > 0 and bool(fb.get("ok"))
verdict = {
    "suite": "wave_c_railway_smoke_v1",
    "pass": ok,
    "health_version": health.get("version"),
    "ingest_ok": health.get("ingest_ok"),
    "edges_with_telemetry": [
        {"edge_id": e.get("edge_id"), "site_id": e.get("site_id")} for e in telem
    ],
    "sensor_stats_roles": sorted({r for r in roles if r}),
    "zone_other_rows": zone_rows,
    "markers": {
        "zone_role": has_zone,
        "bldg2-zone-loopback": has_loop,
        "fieldbus_ok": bool(fb.get("ok")),
    },
}
(art / "verdict.json").write_text(json.dumps(verdict, indent=2) + "\n")
print(json.dumps(verdict, indent=2))
sys.exit(0 if ok else 1)
PY

echo "PASS: Railway Wave C smoke → $ART"
