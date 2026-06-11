#!/usr/bin/env bash
# Acme vm-bbartling — poll ONLY points required by enabled FDD rules (not full GL36 set).
#
#   ./scripts/acme_commission_fdd_minimal.sh
#   POLL_INTERVAL=60 ./scripts/acme_commission_fdd_minimal.sh
#
# Previous broad GL36 poll (~340 pts) is preserved as points.gl36_poll.csv.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
ANSIBLE_DIR="$(cd "$DIR/.." && pwd)"
ROOT="$(cd "$ANSIBLE_DIR/../.." && pwd)"
LOCAL_DIR="${ROOT}/edge_backup/local/acme/vm-bbartling"
PDIR="${LOCAL_DIR}/points_per_device"
FULL_CSV="${LOCAL_DIR}/points.all_enabled.csv"
GL36_CSV="${LOCAL_DIR}/points.gl36_poll.csv"
OUT_CSV="${LOCAL_DIR}/points.csv"
RULES="${LOCAL_DIR}/rules_store.json"
MANIFEST="${LOCAL_DIR}/fdd_minimal_poll.manifest.json"
POLL_INTERVAL="${POLL_INTERVAL:-60}"

[[ -d "$PDIR" ]] || { echo "Missing ${PDIR}" >&2; exit 1; }
[[ -f "$RULES" ]] || { echo "Missing ${RULES}" >&2; exit 1; }

echo "=== Trim device list ==="
"${DIR}/acme_trim_devices.sh"

PY="$(command -v python3)"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}"

if [[ ! -f "$FULL_CSV" ]]; then
  echo "=== Merge enabled discovery → points.all_enabled.csv ==="
  "$PY" -m bacnet_toolshed.merge_points_csv \
    --input-dir "$PDIR" \
    -o "$FULL_CSV" \
    --enabled-only
fi

if [[ -f "$OUT_CSV" && ! -f "$GL36_CSV" ]]; then
  cp -a "$OUT_CSV" "$GL36_CSV"
  echo "Backed up prior points.csv → points.gl36_poll.csv"
fi

echo "=== FDD minimal poll filter (rules_store → points.csv) ==="
"$PY" - <<'PY' "$FULL_CSV" "$RULES" "$OUT_CSV" "$MANIFEST" "$POLL_INTERVAL"
import sys
from pathlib import Path
from bacnet_toolshed.fdd_minimal_poll import filter_points_csv_for_rules

src = Path(sys.argv[1])
rules = Path(sys.argv[2])
dst = Path(sys.argv[3])
manifest = Path(sys.argv[4])
poll_s = int(sys.argv[5])
meta = filter_points_csv_for_rules(
    points_csv=src,
    rules_store=rules,
    output_csv=dst,
    manifest_path=manifest,
    poll_interval_s=poll_s,
)
print(f"points.csv: {meta['matched_rows']} FDD-minimal rows (from {meta['source_rows']} candidates)")
print("brick classes:", ", ".join(f"{k}={v}" for k, v in list(meta['brick_class_counts'].items())[:8]))
print(f"manifest: {manifest}")
PY

echo "Deploy: cd ${ANSIBLE_DIR} && ./deploy.sh --limit acme_vm_bbartling -e openfdd_push_bacnet_config=true"
