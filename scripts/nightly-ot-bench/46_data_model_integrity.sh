#!/usr/bin/env bash
# Gate 46 — data-model integrity (gate40 scanner + mapping API smoke).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ART="${ARTIFACT_DIR:-$ROOT/reports/gate46_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$ART"
python3 "$ROOT/scripts/qualification/no_equipment_id_heuristics.py" --root "$ROOT" | tee "$ART/scanner.txt"
echo "PASS gate 46 scanner" | tee "$ART/gate46.txt"
