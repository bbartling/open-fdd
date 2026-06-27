#!/usr/bin/env bash
# Download LBNL MZVAV synthesis CSV fixtures for local CSV import / FDD practice.
# Source: https://github.com/bbartling/open-fdd/tree/23bbf23/air_handling_unit/ahu_data
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$ROOT/workspace/fixtures/ahu_data"
REF="${OPENFDD_AHU_DATA_REF:-23bbf23}"
BASE="https://raw.githubusercontent.com/bbartling/open-fdd/${REF}/air_handling_unit/ahu_data"
mkdir -p "$DEST"
for f in MZVAV-1.csv MZVAV-2-1.csv MZVAV-2-2.csv; do
  echo "Fetching $f ..."
  curl -fsSL -o "$DEST/$f" "$BASE/$f"
done
echo "Done: $DEST"
wc -l "$DEST"/*.csv
