#!/usr/bin/env bash
# Combined OT MQTT/BACnet + synthetic CSV bulk validation (multi-site isolation).
# Run on an already-up react-ot stack. Honest FAIL if OT LAN is down.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

ART="${ARTIFACT_DIR:-$ROOT/reports/combined_ot_synth_$$}"
mkdir -p "$ART"
export ART
echo "artifacts=$ART"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

capture_ingest() {
  local label="$1"
  ART="$ART" LABEL="$label" python3 - <<'PY'
import json, os, urllib.request
base = os.environ.get("OPENFDD_API_BASE", "http://127.0.0.1:8080")
art = os.environ["ART"]
label = os.environ["LABEL"]
pw = os.environ.get("OPENFDD_ADMIN_PASSWORD", "")
user = os.environ.get("OPENFDD_ADMIN_USER", "admin")
req = urllib.request.Request(
    base + "/api/auth/login",
    data=json.dumps({"username": user, "password": pw}).encode(),
    headers={"Content-Type": "application/json"},
)
token = json.load(urllib.request.urlopen(req, timeout=30))["token"]
for path in ("/api/ingest/stats", "/api/health"):
    r = urllib.request.Request(base + path, headers={"Authorization": f"Bearer {token}"})
    body = urllib.request.urlopen(r, timeout=30).read().decode()
    name = path.strip("/").replace("/", "_")
    open(f"{art}/{label}_{name}.json", "w", encoding="utf-8").write(body)
    print(path, body[:240].replace("\n", " "))
PY
}

echo "==> Baseline ingest/health"
capture_ingest before

echo "==> BACnet OT (02)"
./scripts/nightly-ot-bench/02_bacnet_ot.sh 2>&1 | tee "$ART/02_bacnet_ot.log"

echo "==> MQTT persist (03)"
./scripts/nightly-ot-bench/03_mqtt_feather_persist.sh 2>&1 | tee "$ART/03_mqtt.log"

echo "==> Synthetic CSV bulk (other building)"
python3 scripts/synthetic_59_target_pair_soak.py --side ofdd 2>&1 | tee "$ART/synth_pair.log"
python3 scripts/synthetic_59_overview_analytics_soak.py 2>&1 | tee "$ART/synth_overview.log"
python3 scripts/synthetic_59_health_matrix_fault_hours_soak.py 2>&1 | tee "$ART/synth_health.log"

echo "==> Post-synth ingest/health (MQTT must still be alive)"
capture_ingest after

echo "OK combined validate artifacts in $ART"
