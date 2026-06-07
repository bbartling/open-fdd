#!/usr/bin/env bash
# Trim Acme BACnet device list for GL36 polling scope (control machine only).
#
# Keeps:
#   - JCI VMA/VAV instances 1–100
#   - RTU AHU 1100, hot-water plant 1002
#   - Trane UC210 VAV 11000–13000
# Drops Tracer SC (10000), eGauge, gateways, and all other devices.
#
#   ./scripts/acme_trim_devices.sh
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$DIR/../../.." && pwd)"
LOCAL_DIR="${ROOT}/edge_backup/local/acme/vm-bbartling"
SRC="${LOCAL_DIR}/devices_discovered.csv"
DST="${LOCAL_DIR}/devices_discovered.trim.csv"

[[ -f "$SRC" ]] || { echo "Missing ${SRC} — run BACnet discover on edge first or restore backup" >&2; exit 1; }

python3 - <<'PY' "$SRC" "$DST"
import csv, sys
from pathlib import Path

src, dst = Path(sys.argv[1]), Path(sys.argv[2])

def allowed(inst: int) -> bool:
    if 1 <= inst <= 100:
        return True
    if inst in (1100, 1002):
        return True
    if 11000 <= inst <= 13000:
        return True
    return False

rows = list(csv.DictReader(src.open(newline="", encoding="utf-8")))
out = []
for r in rows:
    try:
        inst = int(str(r.get("device_instance") or "").strip())
    except ValueError:
        continue
    if allowed(inst):
        out.append(r)

if not out:
    raise SystemExit("No devices matched Acme trim rules")

fieldnames = list(rows[0].keys())
with dst.open("w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
    w.writeheader()
    w.writerows(out)

jci = sum(1 for r in out if 1 <= int(r["device_instance"]) <= 100)
trane = sum(1 for r in out if 11000 <= int(r["device_instance"]) <= 13000)
plant = sum(1 for r in out if int(r["device_instance"]) in (1100, 1002))
print(f"devices_discovered.trim.csv: {len(out)} devices (jci={jci} trane={trane} plant={plant})")
print(f"  → {dst}")
PY
