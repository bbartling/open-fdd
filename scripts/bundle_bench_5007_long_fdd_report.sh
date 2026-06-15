#!/usr/bin/env bash
# Zip the latest Bench 5007 long FDD smoke report and delete all older artifacts.
#
#   ./scripts/bundle_bench_5007_long_fdd_report.sh
#   ./scripts/bundle_bench_5007_long_fdd_report.sh --log /tmp/bench_5007_long_fdd_3.1.3.log
#   ./scripts/bundle_bench_5007_long_fdd_report.sh --stamp bench_5007_long_fdd_20260615T184512Z
#
# Output: /tmp/bench_5007_long_fdd_bundle.zip (override with --out)
# Then from Windows PowerShell:
#   scp ben@bensserver:/tmp/bench_5007_long_fdd_bundle.zip C:\Users\ben\Downloads\
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPORTS="${OPENFDD_SMOKE_REPORTS_DIR:-$ROOT/workspace/reports}"
LOG=""
STAMP=""
OUT="/tmp/bench_5007_long_fdd_bundle.zip"
SCP_HOST="${OPENFDD_SCP_HOST:-bensserver}"
SCP_USER="${OPENFDD_SCP_USER:-ben}"

usage() {
  sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --log) LOG="$2"; shift 2 ;;
    --stamp) STAMP="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    -h|--help) usage 0 ;;
    *) echo "Unknown arg: $1" >&2; usage 1 ;;
  esac
done

resolve_stamp() {
  if [[ -n "$STAMP" ]]; then
    echo "$STAMP"
    return
  fi
  if [[ -n "$LOG" && -f "$LOG" ]]; then
    local from_log
    from_log="$(grep -oE 'bench_5007_long_fdd_[0-9]{8}T[0-9]{6}Z' "$LOG" | tail -1 || true)"
    if [[ -n "$from_log" ]]; then
      echo "$from_log"
      return
    fi
  fi
  local newest
  newest="$(find "$REPORTS" -maxdepth 1 -name 'bench_5007_long_fdd_*.json' -printf '%T@ %f\n' 2>/dev/null \
    | sort -nr | head -1 | awk '{print $2}' | sed 's/\.json$//' || true)"
  if [[ -z "$newest" ]]; then
    echo "No bench_5007_long_fdd_*.json under $REPORTS" >&2
    exit 1
  fi
  echo "$newest"
}

STAMP="$(resolve_stamp)"
BASE="$REPORTS/$STAMP"
JSON="${BASE}.json"
MD="${BASE}.md"
CSV="${BASE}_events.csv"

for f in "$JSON"; do
  [[ -f "$f" ]] || { echo "Missing report: $f" >&2; exit 1; }
done

# Remove prior bundle zips for this smoke family
rm -f /tmp/bench_5007_long_fdd_bundle.zip /tmp/bench_5007_long_fdd_3.1.3-live.zip 2>/dev/null || true

PYTHON="${ROOT}/.venv/bin/python"
[[ -x "$PYTHON" ]] || PYTHON=python3

"$PYTHON" - <<PY
import zipfile
from pathlib import Path

stamp = "${STAMP}"
out = Path("${OUT}")
paths = [
    Path("${JSON}"),
    Path("${MD}"),
    Path("${CSV}"),
]
log = Path("${LOG}") if "${LOG}" else None
if log and log.is_file():
    paths.append(log)

with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
    for p in paths:
        if p.is_file():
            zf.write(p, p.name)
            print(f"  + {p.name}")
        else:
            print(f"  (skip missing {p})")

print(f"\nWrote {out} ({out.stat().st_size} bytes)")
PY

DELETED=0
while IFS= read -r -d '' f; do
  rm -f "$f"
  DELETED=$((DELETED + 1))
done < <(find "$REPORTS" -maxdepth 1 -name 'bench_5007_long_fdd_*' -print0 2>/dev/null)

echo ""
echo "Bundled stamp: $STAMP"
echo "Deleted $DELETED old file(s) under $REPORTS"
echo ""
echo "Download from Windows PowerShell:"
echo "  scp ${SCP_USER}@${SCP_HOST}:${OUT} C:\\Users\\ben\\Downloads\\"
