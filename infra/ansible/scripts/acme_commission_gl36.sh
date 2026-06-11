#!/usr/bin/env bash
# Commission Acme trim devices for GL36 / economizer FDD passive polling (60s).
# Keeps originals: points_per_device/*.csv, points.all_enabled.csv, points.temp_only.csv
#
# NOTE: Prefer FDD-minimal poll (rules-bound only):
#   ./scripts/acme_commission_fdd_minimal.sh
# This script writes the broader GL36 brick/tag set (~340 points) — avoid on production edge.
#   ./scripts/acme_commission_gl36.sh
#   POLL_INTERVAL=60 ./scripts/acme_commission_gl36.sh
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
ANSIBLE_DIR="$(cd "$DIR/.." && pwd)"
ROOT="$(cd "$ANSIBLE_DIR/../.." && pwd)"
LOCAL_DIR="${ROOT}/edge_backup/local/acme/vm-bbartling"
PDIR="${LOCAL_DIR}/points_per_device"
DEVICES="${LOCAL_DIR}/devices_discovered.trim.csv"
POLL_INTERVAL="${POLL_INTERVAL:-60}"
FULL_CSV="${LOCAL_DIR}/points.all_enabled.csv"
GL36_CSV="${LOCAL_DIR}/points.gl36_poll.csv"
OUT_CSV="${LOCAL_DIR}/points.csv"

[[ -d "$PDIR" ]] || { echo "Missing ${PDIR}" >&2; exit 1; }

echo "=== Trim device list (JCI 1–100, plant 1100/1002, Trane 11000–13000) ==="
"${DIR}/acme_trim_devices.sh"

PY="$(command -v python3)"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}"

if [[ ! -f "$FULL_CSV" ]]; then
  echo "=== Merge enabled points → points.all_enabled.csv (bacnet_toolshed) ==="
  "$PY" -m bacnet_toolshed.merge_points_csv \
    --input-dir "$PDIR" \
    -o "$FULL_CSV" \
    --enabled-only
fi

echo "=== Filter GL36 / VAV-AHU / economizer poll set → points.csv ==="
"$PY" - <<'PY' "$FULL_CSV" "$GL36_CSV" "$OUT_CSV"
import csv, sys
from pathlib import Path

src, gl36_copy, dst = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])

# ASHRAE GL36 Trim & Respond + economizer diagnostics (passive poll only)
GL36_BRICK = {
    "Zone_Air_Temperature_Sensor",
    "Zone_Air_Temperature_Setpoint",
    "Discharge_Air_Temperature_Sensor",
    "Supply_Air_Temperature_Sensor",
    "Return_Air_Temperature_Sensor",
    "Outside_Air_Temperature_Sensor",
    "Mixed_Air_Temperature_Sensor",
    "Outside_Air_Humidity_Sensor",
    "Return_Air_Humidity_Sensor",
    "Supply_Air_Static_Pressure_Sensor",
    "Supply_Air_Static_Pressure_Setpoint",
    "Discharge_Air_Temperature_Setpoint",
    "Supply_Air_Flow_Sensor",
    "Supply_Air_Flow_Setpoint",
    "Damper_Position_Sensor",
    "Damper_Position_Command",
    "Outside_Air_Damper_Command",
    "Heating_Valve_Command",
    "Cooling_Command",
    "Cooling_Temperature_Setpoint",
    "Heating_Temperature_Setpoint",
    "Supply_Fan_Speed_Command",
    "Return_Fan_Speed_Command",
}

GL36_TAGS = {
    "ZN-T", "ZN-SP", "DA-T", "SAT", "RAT", "OAT", "MAT", "OAH", "RAH", "SAP", "SAP-SP",
    "DAT-SP", "SAT-SP",
    "SA-F", "SAFLOW-SP", "DPR-O", "DPR-CMD", "DPR-STAT", "OAD-CMD", "CLG-O",
    "HTG-O", "CLG-STAT", "SF-CMD", "RF-CMD", "EFFCLG-SP", "EFFHTG-SP",
    "HWS-Plant-Requests",
}

NAME_HINTS = (
    "hot water", "boiler", "pump vfd", "firing rate", "differential pressure",
    "plant request", "compressor", "supply fan", "return fan",
)

rows = list(csv.DictReader(src.open(newline="", encoding="utf-8")))

def gl36_row(r: dict) -> bool:
    bc = (r.get("brick_class") or "").strip()
    tag = (r.get("brick_tag") or "").strip()
    name = (r.get("object_name") or "").lower()
    sid = (r.get("system_id") or "").lower()
    if bc in GL36_BRICK or tag in GL36_TAGS:
        return True
    if sid == "rtu-01" and any(
        h in name
        for h in (
            "duct static pressure setpoint",
            "discharge air temperature setpoint",
            "discharge air cooling setpoint",
            "discharge air heating setpoint",
        )
    ):
        return True
    if sid in ("rtu-01", "hw-plant", "tracer-sc") and any(h in name for h in NAME_HINTS):
        return True
    if bc == "Supply_Air_Temperature_Sensor" and sid == "hw-plant":
        return "hot water" in name or "boiler" in name
    return False

out = [r for r in rows if gl36_row(r)]
if not out:
    raise SystemExit("No GL36 poll rows matched")

fieldnames = list(out[0].keys())
for path in (gl36_copy, dst):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(out)

vav = {r["device_instance"] for r in out if "vav" in (r.get("system_id") or "")}
by_class: dict[str, int] = {}
for r in out:
    by_class[r.get("brick_class", "?")] = by_class.get(r.get("brick_class", ""), 0) + 1
print(f"points.csv: {len(out)} GL36 rows across {len(vav)} VAV devices")
print("brick_class counts:", ", ".join(f"{k}={v}" for k, v in sorted(by_class.items(), key=lambda x: -x[1])[:12]))
print(f"Backup: {gl36_copy}")
PY

echo "Deploy: cd ${ANSIBLE_DIR} && ./deploy.sh --limit acme_vm_bbartling"
