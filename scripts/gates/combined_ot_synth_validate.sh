#!/usr/bin/env bash
# Combined OT MQTT/BACnet + synthetic CSV bulk validation (multi-site isolation)
# + per-edge Suspend telemetry (poll/weather/MQTT gated; BACnet server kept).
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

FIELDBUS_BASE="${FIELDBUS_BASE:-http://127.0.0.1:8081}"
FB_KEY="${OPENFDD_FIELDBUS_API_KEY:-bench-demo-key-1234567890}"

fb() {
  curl -fsS --max-time 30 -H "Authorization: Bearer ${FB_KEY}" -H "Content-Type: application/json" "$@"
}

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

echo "==> Modbus OT (04) — Pi sim @ MODBUS_SIM_HOST"
./scripts/nightly-ot-bench/04_modbus_ot.sh 2>&1 | tee "$ART/04_modbus.log"

echo "==> Haystack (05) — live if HAYSTACK_EXPECT_LIVE=1"
./scripts/nightly-ot-bench/05_haystack.sh 2>&1 | tee "$ART/05_haystack.log"

echo "==> Suspend telemetry (fieldbus REST)"
STATUS="$(fb "$FIELDBUS_BASE/telemetry/status")"
echo "$STATUS" | tee "$ART/telemetry_before.json"
echo "$STATUS" | python3 -c 'import json,sys; s=json.load(sys.stdin); assert s.get("ok") is True; assert s.get("suspended") is False, s'
SUSPEND="$(fb -X POST "$FIELDBUS_BASE/telemetry/suspend" -d '{"approved_by":"combined-validate"}')"
echo "$SUSPEND" | tee "$ART/telemetry_suspended.json"
echo "$SUSPEND" | python3 -c 'import json,sys; s=json.load(sys.stdin); assert s.get("suspended") is True, s; assert s.get("poll_running") is False, s; assert s.get("bacnet_server_kept") is True, s'
# Hosted BACnet server must still answer while poll is stopped.
OBJECTS="$(fb "$FIELDBUS_BASE/bacnet/server/objects")"
echo "$OBJECTS" | tee "$ART/telemetry_server_objects.json"
echo "$OBJECTS" | python3 -c 'import json,sys; s=json.load(sys.stdin); assert isinstance(s, (dict, list)), s'
POLL="$(fb "$FIELDBUS_BASE/bacnet/poll/status")"
echo "$POLL" | tee "$ART/telemetry_poll_while_suspended.json"
echo "$POLL" | python3 -c 'import json,sys; s=json.load(sys.stdin); assert s.get("running") is False, s'
RESUME="$(fb -X POST "$FIELDBUS_BASE/telemetry/resume" -d '{"approved_by":"combined-validate"}')"
echo "$RESUME" | tee "$ART/telemetry_resumed.json"
echo "$RESUME" | python3 -c 'import json,sys; s=json.load(sys.stdin); assert s.get("suspended") is False, s'
# Force a poll cycle so OT ingest can advance again after resume.
fb -X POST "$FIELDBUS_BASE/bacnet/poll/once" >/dev/null
echo "OK suspend/resume telemetry"

echo "==> Synthetic CSV bulk (other building)"
python3 scripts/synthetic_59_target_pair_soak.py --side ofdd 2>&1 | tee "$ART/synth_pair.log"
python3 scripts/synthetic_59_overview_analytics_soak.py 2>&1 | tee "$ART/synth_overview.log"
python3 scripts/synthetic_59_health_matrix_fault_hours_soak.py 2>&1 | tee "$ART/synth_health.log"

echo "==> Post-synth ingest/health (MQTT must still be alive)"
capture_ingest after

echo "OK combined validate artifacts in $ART"
