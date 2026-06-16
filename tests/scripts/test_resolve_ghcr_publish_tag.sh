#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck source=/dev/null
source "${ROOT}/scripts/resolve_ghcr_publish_tag.sh"

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
printf '%s\n' 'version = "3.1.3"' >"$tmp"

ver="$(resolve_ghcr_publish_tag "master" "" "$tmp")"
[[ "$ver" == "3.1.3" ]] || { echo "expected 3.1.3 from pyproject, got $ver"; exit 1; }

ver="$(resolve_ghcr_publish_tag "v3.1.4" "" "$tmp")"
[[ "$ver" == "3.1.4" ]] || { echo "expected 3.1.4 from tag, got $ver"; exit 1; }

ver="$(resolve_ghcr_publish_tag "master" "3.2.0" "$tmp")"
[[ "$ver" == "3.2.0" ]] || { echo "expected override 3.2.0, got $ver"; exit 1; }

ghcr_publish_release_tags_enabled "v3.1.3" "push" || { echo "tag push should enable release tags"; exit 1; }
ghcr_publish_release_tags_enabled "master" "workflow_dispatch" || { echo "dispatch should enable release tags"; exit 1; }
ghcr_publish_release_tags_enabled "master" "push" && { echo "plain push should not enable release tags"; exit 1; }

echo "resolve_ghcr_publish_tag ok"
