#!/usr/bin/env bash
# Dry-run driver_tree → fieldbus migration; fail on fatal 599999 hosting conflicts.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

REPORT_DIR="${OPENFDD_MIGRATION_REPORT_DIR:-$ROOT/reports}"
REPORT="$REPORT_DIR/migration-report.json"
MIGRATOR="$ROOT/scripts/migrate_driver_tree_to_fieldbus.py"
TREE="${OPENFDD_DRIVER_TREE:-$ROOT/workspace/data/drivers/bacnet/driver_tree.json}"

mkdir -p "$REPORT_DIR"

echo "== Open-FDD dry-run migration report =="
echo "driver_tree=$TREE"
echo "report=$REPORT"

if [[ ! -f "$MIGRATOR" ]]; then
  echo "ERROR: missing migrator: $MIGRATOR" >&2
  exit 1
fi

if [[ ! -f "$TREE" ]]; then
  echo "WARN: driver tree not found — writing empty migration report"
  python3 - "$REPORT" "$TREE" <<'PY'
import json
import sys
from pathlib import Path

report_path = Path(sys.argv[1])
tree_path = sys.argv[2]
report = {
    "ok": True,
    "source": tree_path,
    "bacnet_devices_found": 0,
    "field_devices_toml_blocks": 0,
    "field_devices_toml": "",
    "unresolved": [
        {
            "severity": "info",
            "reason": "driver tree missing — nothing to migrate",
            "path": tree_path,
        }
    ],
    "fatal_unresolved": [],
    "next_steps": [
        "Commission BACnet devices in openfdd-fieldbus config/fieldbus/",
        "Re-run this script after exporting driver_tree.json from the legacy stack",
    ],
}
report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(f"wrote {report_path}")
PY
else
  python3 "$MIGRATOR" "$TREE" --report "$REPORT"
fi

if [[ ! -f "$REPORT" ]]; then
  echo "ERROR: migration report not created: $REPORT" >&2
  exit 1
fi

echo "Analyzing report for fatal 599999 hosting conflicts..."
python3 - "$REPORT" <<'PY'
import json
import sys
from pathlib import Path

report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
unresolved = report.get("unresolved") or []
fatal = report.get("fatal_unresolved") or []

HOSTED = {"599999", "599_999"}
SKIP_PHRASE = "skipped local server device"

def is_hosted_conflict(entry: dict) -> bool:
    inst = str(entry.get("device_instance", "")).strip()
    reason = str(entry.get("reason", "")).lower()
    severity = str(entry.get("severity", "")).lower()
    if "conflict" in reason and inst in HOSTED:
        return True
    if severity == "fatal" and inst in HOSTED:
        return True
    if inst in HOSTED and SKIP_PHRASE not in reason:
        # Mapped or unresolved 599999 outside the expected skip is a hosting conflict.
        if any(
            k in reason
            for k in (
                "duplicate",
                "collision",
                "break",
                "hosted server",
                "cannot host",
                "unmapped bacnet point",
            )
        ):
            return True
    return False

conflicts = [e for e in unresolved if is_hosted_conflict(e)]
conflicts.extend(e for e in fatal if isinstance(e, dict))

if conflicts:
    print("FATAL: unresolved entries conflict with hosted BACnet device 599999:", file=sys.stderr)
    for entry in conflicts:
        print(f"  - {entry.get('reason', entry)}", file=sys.stderr)
    sys.exit(1)

print("OK: no fatal 599999 hosting conflicts in migration report")
PY

echo "PASS: dry-run migration report at $REPORT"
