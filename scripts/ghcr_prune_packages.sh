#!/usr/bin/env bash
# Prune GHCR container packages for Open-FDD edge images.
#
#   ./scripts/ghcr_prune_packages.sh              # keep 3 versions per active package
#   ./scripts/ghcr_prune_packages.sh --keep 3
#   ./scripts/ghcr_prune_packages.sh --delete-retired   # remove openfdd-bacnet-poll entirely
#
# Requires: gh auth login with read:packages and delete:packages (or repo admin).
set -euo pipefail

OWNER="${GHCR_OWNER:-bbartling}"
KEEP="${GHCR_KEEP_VERSIONS:-3}"
DELETE_RETIRED=false
ACTIVE=(openfdd-bridge openfdd-commission openfdd-mcp-rag)
RETIRED=openfdd-bacnet-poll

while [[ $# -gt 0 ]]; do
  case "$1" in
    --keep) KEEP="$2"; shift 2 ;;
    --delete-retired) DELETE_RETIRED=true; shift ;;
    -h|--help)
      sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

_api() {
  gh api "$@" 2>&1
}

_delete_version() {
  local pkg="$1" id="$2"
  echo "    delete version id=${id}"
  _api -X DELETE "users/${OWNER}/packages/container/${pkg}/versions/${id}" >/dev/null
}

_prune_package() {
  local pkg="$1"
  echo "==> ${pkg} (keep ${KEEP} newest)"
  local versions_json
  if ! versions_json="$(_api "users/${OWNER}/packages/container/${pkg}/versions?per_page=100")"; then
    echo "WARN: cannot list ${pkg} — ${versions_json}" >&2
    return 0
  fi
  local ids
  ids="$(echo "$versions_json" | python3 -c "
import json, sys
rows = json.load(sys.stdin)
rows.sort(key=lambda r: r.get('updated_at') or r.get('created_at') or '', reverse=True)
for r in rows[${KEEP}:]:
    print(r['id'])
")"
  if [[ -z "$ids" ]]; then
    echo "    nothing to prune"
    return 0
  fi
  while IFS= read -r id; do
    [[ -n "$id" ]] && _delete_version "$pkg" "$id"
  done <<<"$ids"
}

_delete_retired_package() {
  echo "==> Delete retired package: ${RETIRED}"
  if _api -X DELETE "users/${OWNER}/packages/container/${RETIRED}" >/dev/null 2>&1; then
    echo "    removed ${RETIRED}"
    return 0
  fi
  echo "    package not found or already deleted — pruning versions if any"
  local versions_json
  if versions_json="$(_api "users/${OWNER}/packages/container/${RETIRED}/versions?per_page=100" 2>/dev/null)"; then
    echo "$versions_json" | python3 -c "
import json, sys
for r in json.load(sys.stdin):
    print(r['id'])
" | while IFS= read -r id; do
      [[ -n "$id" ]] && _delete_version "$RETIRED" "$id"
    done
    _api -X DELETE "users/${OWNER}/packages/container/${RETIRED}" >/dev/null 2>&1 || true
  fi
}

echo "=== GHCR prune (owner=${OWNER}) ==="
if [[ "$DELETE_RETIRED" == true ]]; then
  _delete_retired_package
fi
for pkg in "${ACTIVE[@]}"; do
  _prune_package "$pkg"
done
echo "Done."
