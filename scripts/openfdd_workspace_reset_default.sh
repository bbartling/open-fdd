#!/usr/bin/env bash
# Reset local workspace to the default empty model.
# Deletes CSV import artifacts under the workspace. Does not touch Timescale.
# Refuses unless --i-understand-data-loss or OPENFDD_ALLOW_DESTRUCTIVE_DB=1.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/data_safe.sh
source "$ROOT/scripts/lib/data_safe.sh"
WS="${OPENFDD_WORKSPACE:-$ROOT/workspace}"
ACK=0
DRY_RUN=0
if openfdd_env_flag_on "${OPENFDD_ALLOW_DESTRUCTIVE_DB:-}"; then
  ACK=1
fi
while [[ $# -gt 0 ]]; do
  case "$1" in
    --i-understand-data-loss) ACK=1 ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help)
      echo "Usage: $0 [--dry-run] --i-understand-data-loss"
      echo "Or set OPENFDD_ALLOW_DESTRUCTIVE_DB=1. Default is to refuse."
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done
if [[ "$ACK" != "1" ]]; then
  echo "REFUSING workspace reset. Pass --i-understand-data-loss or set OPENFDD_ALLOW_DESTRUCTIVE_DB=1." >&2
  echo "data_safe_action=refuse" >&2
  exit 2
fi
if [[ "$DRY_RUN" == "1" ]]; then
  echo "data_safe_action=reset_workspace"
  exit 0
fi
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
