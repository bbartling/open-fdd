#!/usr/bin/env bash
# Reset local workspace to default empty model — removes CSV import artifacts (never committed to git).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WS="${OPENFDD_WORKSPACE:-$ROOT/workspace}"
DEFAULT_MODEL="$ROOT/workspace/model/default_haystack_grid.json"
MODEL_DIR="$WS/data/model"

echo "Open-FDD workspace reset (default local model)"
echo "  workspace: $WS"

if [[ ! -d "$WS" ]]; then
  echo "error: workspace not found at $WS" >&2
  exit 1
fi

if [[ ! -f "$DEFAULT_MODEL" ]]; then
  echo "error: missing $DEFAULT_MODEL" >&2
  exit 1
fi

rm -rf "$WS/data/csv_import_sessions"/* 2>/dev/null || true
rm -rf "$WS/data/datasets"/* 2>/dev/null || true
rm -rf "$WS/data/csv_workbench"/* 2>/dev/null || true
mkdir -p "$WS/data/csv_import_sessions" "$WS/data/datasets" "$WS/data/csv_workbench" "$MODEL_DIR"

echo '{"datasets":[]}' >"$WS/data/datasets/registry.json"

cp "$DEFAULT_MODEL" "$MODEL_DIR/haystack_grid.json"
if [[ -f "$MODEL_DIR/assignments.json" ]]; then
  echo '{"points":[],"rules":[]}' >"$MODEL_DIR/assignments.json"
fi

# Clear historian pivot rows sourced from CSV imports (keep dir structure).
find "$WS/data/historian" -name 'telemetry_pivot.jsonl' -delete 2>/dev/null || true
find "$WS/data/historian" -name '*.feather' -delete 2>/dev/null || true
find "$WS/data/historian" -name '*.arrow' -delete 2>/dev/null || true

echo "Done. Default model: site:local only. Restart edge or refresh Model tab."
