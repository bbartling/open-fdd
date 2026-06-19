#!/usr/bin/env bash
# Zip paired FDD smoke artifacts for download from Windows.
#
#   ./scripts/bundle_paired_fdd_smoke_report.sh
#   ./scripts/bundle_paired_fdd_smoke_report.sh --mode overnight
#   ./scripts/bundle_paired_fdd_smoke_report.sh --log /tmp/paired_fdd_smoke_overnight_20260616_202728.log
#
# Output: /tmp/paired_fdd_smoke_bundle.zip
# Then from Windows PowerShell (Tailscale):
#   scp ben@bensserver:/tmp/paired_fdd_smoke_bundle.zip C:\Users\ben\Downloads\
# Or LAN:
#   scp ben@192.168.204.18:/tmp/paired_fdd_smoke_bundle.zip C:\Users\ben\Downloads\
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODE="overnight"
LOG=""
OUT="/tmp/paired_fdd_smoke_bundle.zip"
SCP_HOST="${OPENFDD_SCP_HOST:-bensserver}"
SCP_USER="${OPENFDD_SCP_USER:-ben}"

usage() {
  sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) MODE="$2"; shift 2 ;;
    --log) LOG="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    -h|--help) usage 0 ;;
    *) echo "Unknown arg: $1" >&2; usage 1 ;;
  esac
done

if [[ -z "$LOG" ]]; then
  LOG="$(ls -t /tmp/paired_fdd_smoke_${MODE}_*.log 2>/dev/null | head -1 || true)"
fi

STATUS="/tmp/paired_fdd_smoke_${MODE}.status.json"
CYCLES="/tmp/paired_fdd_smoke_${MODE}_cycles.jsonl"
MD="$ROOT/reports/paired_fdd_smoke_validation.md"
JSON="$ROOT/reports/paired_fdd_smoke_validation.json"
PARITY="$ROOT/reports/site_parity_smoke.json"

missing=0
for f in "$MD" "$JSON"; do
  [[ -f "$f" ]] || { echo "Missing: $f" >&2; missing=1; }
done
[[ $missing -eq 0 ]] || exit 1

rm -f "$OUT" 2>/dev/null || true

PYTHON="${ROOT}/.venv/bin/python3"
[[ -x "$PYTHON" ]] || PYTHON=python3

"$PYTHON" - <<PY
import zipfile
from pathlib import Path

out = Path("${OUT}")
paths = [
    Path("${MD}"),
    Path("${JSON}"),
    Path("${PARITY}"),
    Path("${STATUS}"),
    Path("${CYCLES}"),
]
log = Path("${LOG}") if "${LOG}" else None
if log and log.is_file():
    paths.append(log)

with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
    for p in paths:
        if p.is_file():
            zf.write(p, p.name)
            print(f"  + {p.name} ({p.stat().st_size} bytes)")
        else:
            print(f"  (skip missing {p})")

print(f"\nWrote {out} ({out.stat().st_size} bytes)")
PY

echo ""
echo "Bundled mode: ${MODE}"
[[ -n "$LOG" && -f "$LOG" ]] && echo "Log: $LOG"
echo ""
echo "Download from Windows PowerShell (Tailscale — use this from anywhere):"
echo "  scp ${SCP_USER}@${SCP_HOST}:${OUT} C:\\Users\\ben\\Downloads\\"
echo ""
echo "Or LAN (same subnet as bensserver):"
echo "  scp ${SCP_USER}@192.168.204.18:${OUT} C:\\Users\\ben\\Downloads\\"
echo ""
echo "Unpack:"
echo "  Expand-Archive -Path \$env:USERPROFILE\\Downloads\\paired_fdd_smoke_bundle.zip -DestinationPath \$env:USERPROFILE\\Downloads\\paired_fdd_smoke_bundle -Force"
