#!/usr/bin/env bash
# Enable BRICK tags + 60s poll on Acme trim devices; merge temp sensors only (2 per VAV typical).
#
# Preserves original points_per_device/*.csv — writes filtered points.csv for edge deploy.
#
#   ./scripts/acme_commission_temp.sh
#   POLL_INTERVAL=60 ./scripts/acme_commission_temp.sh
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
ANSIBLE_DIR="$(cd "$DIR/.." && pwd)"
ROOT="$(cd "$ANSIBLE_DIR/../.." && pwd)"
VIBE_ROOT="${VIBE12_ROOT:-$HOME/py-bacnet-stacks-playground/vibe_code_apps_12}"

LOCAL_DIR="${ROOT}/edge_backup/local/acme/vm-bbartling"
PDIR="${LOCAL_DIR}/points_per_device"
DEVICES="${LOCAL_DIR}/devices_discovered.trim.csv"
POLL_INTERVAL="${POLL_INTERVAL:-60}"

[[ -d "$PDIR" ]] || { echo "Missing ${PDIR} — sync edge_backup first" >&2; exit 1; }
[[ -f "$DEVICES" ]] || { echo "Missing ${DEVICES}" >&2; exit 1; }

PY="${VIBE_ROOT}/.venv/bin/python"
[[ -x "$PY" ]] || PY="$(command -v python3)"
export PYTHONPATH="${VIBE_ROOT}${PYTHONPATH:+:$PYTHONPATH}"

echo "=== Commission enable (${POLL_INTERVAL}s, BRICK tags, trim devices) ==="
"$PY" -m edge_bacnet.commission_enable \
  --dir "$PDIR" \
  --devices-csv "$DEVICES" \
  --only-in-devices-csv \
  --poll-interval "$POLL_INTERVAL" \
  --site-id acme \
  --building-id vm-bbartling

echo "=== Merge all enabled rows (full backup copy) ==="
FULL_CSV="${LOCAL_DIR}/points.all_enabled.csv"
"$PY" -m edge_bacnet.merge_points_csv \
  --input-dir "$PDIR" \
  -o "$FULL_CSV" \
  --enabled-only

echo "=== Filter temperature sensors → points.csv (edge poll list) ==="
"$PY" - <<'PY' "$FULL_CSV" "${LOCAL_DIR}/points.csv"
import csv, sys
from pathlib import Path

src, dst = Path(sys.argv[1]), Path(sys.argv[2])
TEMP_CLASSES = {
    "Zone_Air_Temperature_Sensor",
    "Discharge_Air_Temperature_Sensor",
    "Supply_Air_Temperature_Sensor",
    "Return_Air_Temperature_Sensor",
    "Outside_Air_Temperature_Sensor",
    "Mixed_Air_Temperature_Sensor",
}
rows = list(csv.DictReader(src.open(newline="", encoding="utf-8")))
out = [r for r in rows if (r.get("brick_class") or "") in TEMP_CLASSES]
if not out:
    raise SystemExit("No temperature sensor rows after filter")
fieldnames = list(out[0].keys())
with dst.open("w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
    w.writeheader()
    w.writerows(out)

vav = {r["device_instance"] for r in out if "vav" in (r.get("system_id") or "")}
zat = sum(1 for r in out if r.get("brick_class") == "Zone_Air_Temperature_Sensor")
dat = sum(1 for r in out if r.get("brick_class") == "Discharge_Air_Temperature_Sensor")
print(f"points.csv: {len(out)} temp rows ({zat} ZN-T, {dat} DA-T) across {len(vav)} VAV-ish devices")
print(f"Full enabled backup: {src}")
PY

echo "Done. Deploy with:"
echo "  cd ${ANSIBLE_DIR} && ./deploy.sh --limit acme_vm_bbartling -e enable_bacnet_poll_driver=true"
