#!/usr/bin/env bash
# Reset local workspace scratch to the default empty model.
# Refuses unless --reset-db --i-understand-data-loss or OPENFDD_ALLOW_DESTRUCTIVE_DB=1.
# Does not drop Timescale. Removes CSV import artifacts under OPENFDD_WORKSPACE.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_data_safety.sh
source "$ROOT/scripts/openfdd_data_safety.sh"

RESET_DB=0
UNDERSTAND=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --reset-db) RESET_DB=1 ;;
    --i-understand-data-loss) UNDERSTAND=1 ;;
    -h|--help)
      cat <<'EOF'
Usage: openfdd_workspace_reset_default.sh --reset-db --i-understand-data-loss

Refuses by default. Deletes local workspace CSV import scratch and legacy
historian files under OPENFDD_WORKSPACE. Does not drop Timescale.

Opt in with both flags, or OPENFDD_ALLOW_DESTRUCTIVE_DB=1.
EOF
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

if ! openfdd_data_loss_opt_in "$RESET_DB" "$UNDERSTAND"; then
  echo "REFUSED: workspace reset would delete local historian scratch." >&2
  echo "Re-run with --reset-db --i-understand-data-loss or OPENFDD_ALLOW_DESTRUCTIVE_DB=1." >&2
  exit 2
fi
echo "WARNING: DATA LOSS — resetting local workspace scratch. Timescale is not dropped." >&2

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
