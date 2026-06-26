#!/usr/bin/env bash
# Safely remove scoped local validation artifacts before a new controlled run.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIRM_PHRASE="DELETE_VALIDATION_ARTIFACTS"

ALLOWED_PREFIXES=(
  "$ROOT/workspace/logs/live_fdd_validation_"
  "$ROOT/workspace/logs/ui_smoke_"
  "$ROOT/workspace/logs/haystack_smoke_"
  "$ROOT/workspace/logs/modbus_smoke_"
  "$ROOT/workspace/logs/one_hour_validation_"
  "$ROOT/workspace/reports/generated/"
  "$ROOT/workspace/reports/validation/"
  "$ROOT/workspace/imports/validation/"
  "$ROOT/workspace/exports/validation/"
  "$ROOT/workspace/data/validation/"
  "$ROOT/workspace/historian/validation/"
  "$ROOT/workspace/feather/validation/"
  "$ROOT/workspace/arrow/validation/"
)

FORBIDDEN_PREFIXES=(
  "$ROOT/workspace/auth.env.local"
  "$ROOT/workspace/bootstrap_credentials.once.txt"
  "$ROOT/workspace/smoke-profiles/"
  "$ROOT/workspace/haystack/local.nhaystack.toml"
  "$ROOT/workspace/data/"
  "$ROOT/workspace/logs/"
)

is_allowed() {
  local path="$1"
  local p
  for p in "${ALLOWED_PREFIXES[@]}"; do
    [[ "$path" == "$p"* ]] && return 0
  done
  return 1
}

is_forbidden_broad() {
  local path="$1"
  [[ "$path" == "$ROOT/workspace" ]] && return 0
  [[ "$path" == "$ROOT/workspace/logs" ]] && return 0
  [[ "$path" == "$ROOT" ]] && return 0
  return 1
}

collect_targets() {
  local glob path
  for glob in \
    "$ROOT/workspace/logs/live_fdd_validation_"* \
    "$ROOT/workspace/logs/ui_smoke_"* \
    "$ROOT/workspace/logs/haystack_smoke_"* \
    "$ROOT/workspace/logs/modbus_smoke_"* \
    "$ROOT/workspace/logs/one_hour_validation_"* \
    "$ROOT/workspace/reports/validation" \
    "$ROOT/workspace/imports/validation" \
    "$ROOT/workspace/exports/validation" \
    "$ROOT/workspace/data/validation" \
    "$ROOT/workspace/historian/validation" \
    "$ROOT/workspace/feather/validation" \
    "$ROOT/workspace/arrow/validation"; do
    for path in $glob; do
      [[ -e "$path" ]] || continue
      if is_forbidden_broad "$path"; then
        echo "REFUSE broad path: $path" >&2
        exit 1
      fi
      if is_allowed "$path"; then
        printf '%s\n' "$path"
      else
        echo "REFUSE non-scoped path: $path" >&2
        exit 1
      fi
    done
  done
  if [[ -d "$ROOT/workspace/reports/generated" ]]; then
    find "$ROOT/workspace/reports/generated" -mindepth 1 -maxdepth 1 -print 2>/dev/null || true
  fi
}

DRY_RUN=1
if [[ "${1:-}" == "--confirm" && "${2:-}" == "$CONFIRM_PHRASE" ]]; then
  DRY_RUN=0
elif [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
else
  echo "Usage: $0 --dry-run" >&2
  echo "       $0 --confirm $CONFIRM_PHRASE" >&2
  exit 1
fi

mapfile -t TARGETS < <(collect_targets | sort -u)
if [[ ${#TARGETS[@]} -eq 0 ]]; then
  echo "No validation artifacts matched scoped prefixes."
  exit 0
fi

echo "Scoped validation cleanup (${#TARGETS[@]} paths):"
for t in "${TARGETS[@]}"; do
  echo "  $t"
done

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "Dry-run only — re-run with: $0 --confirm $CONFIRM_PHRASE"
  exit 0
fi

for t in "${TARGETS[@]}"; do
  rm -rf "$t"
done
echo "Removed ${#TARGETS[@]} scoped validation artifact paths."
