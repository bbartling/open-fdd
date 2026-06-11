#!/usr/bin/env bash
# Safe GHCR container package retention cleanup (dry-run by default).
#
#   ./scripts/ghcr_prune_packages.sh --dry-run
#   ./scripts/ghcr_prune_packages.sh --all-images --dry-run --json-out reports/ghcr-prune-plan.json
#   ./scripts/ghcr_prune_packages.sh --confirm-delete --current-acme-tag v3.0.31
#
# Legacy (docker-publish.yml post-release prune):
#   ./scripts/ghcr_prune_packages.sh --delete-retired --keep-releases 3 --confirm-delete
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${ROOT}/scripts/ghcr_prune_packages.py"

DELETE_RETIRED=false
LEGACY_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --delete-retired)
      DELETE_RETIRED=true
      shift
      ;;
    --keep)
      LEGACY_ARGS+=(--keep-releases "$2")
      shift 2
      ;;
    -h|--help)
      sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
      python3 "$PY" --help
      exit 0
      ;;
    *)
      LEGACY_ARGS+=("$1")
      shift
      ;;
  esac
done

if [[ ${#LEGACY_ARGS[@]} -eq 0 ]]; then
  LEGACY_ARGS=(--all-images --dry-run)
fi

# Default dry-run when neither --confirm-delete nor --dry-run passed
if [[ " ${LEGACY_ARGS[*]} " != *" --confirm-delete "* && " ${LEGACY_ARGS[*]} " != *" --dry-run "* ]]; then
  LEGACY_ARGS=(--dry-run "${LEGACY_ARGS[@]}")
fi

python3 "$PY" "${LEGACY_ARGS[@]}"
status=$?

if [[ "$DELETE_RETIRED" == true ]]; then
  echo "==> Delete retired package: openfdd-bacnet-poll (legacy)"
  if command -v gh >/dev/null 2>&1; then
    gh api -X DELETE "users/${GHCR_OWNER:-bbartling}/packages/container/openfdd-bacnet-poll" 2>/dev/null || \
      echo "    (package not found or already deleted)"
  fi
fi

exit "$status"
