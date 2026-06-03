#!/usr/bin/env bash
# Apply bensserver bench poll + BRICK model (4 BACnet points on device 5007 @ 2000:7).
#
#   ./scripts/apply_bench_four_points.sh
#   ./scripts/apply_bench_four_points.sh --import-model   # also import model + rules + sync TTL
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VENV="${ROOT}/.venv"
SRC_POINTS="${ROOT}/edge_config/demo/bens-office/points.csv"
DST_POINTS="${ROOT}/workspace/bacnet/commissioning/points.csv"
IMPORT=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --import-model) IMPORT=1; shift ;;
    -h|--help)
      echo "Usage: $0 [--import-model]"
      exit 0
      ;;
    *) echo "Unknown: $1" >&2; exit 1 ;;
  esac
done

[[ -f "$SRC_POINTS" ]] || { echo "Missing $SRC_POINTS" >&2; exit 1; }
mkdir -p "$(dirname "$DST_POINTS")"
cp -a "$SRC_POINTS" "$DST_POINTS"
echo "OK — poll driver points.csv → 4 enabled rows ($(wc -l < "$DST_POINTS") lines)"

if [[ "$IMPORT" == 1 ]]; then
  export OPENFDD_REPO_ROOT="$ROOT"
  export OPENFDD_WORKSPACE_DIR="${ROOT}/workspace"
  export OFDD_DESKTOP_DATA_DIR="${ROOT}/workspace/data"
  export PYTHONPATH="${ROOT}:${ROOT}/workspace/api"
  "${VENV}/bin/python" scripts/setup_bench_afdd.py
  echo "OK — bench model (4 points) + rules imported; TTL synced"
fi
