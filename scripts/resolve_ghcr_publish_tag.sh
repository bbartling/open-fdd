#!/usr/bin/env bash
# Resolve GHCR image tags for docker-publish.yml.
#
# Tag push vX.Y.Z / open-fdd-vX.Y.Z → X.Y.Z (+ minor alias + latest in workflow).
# workflow_dispatch → version from pyproject.toml (+ minor + latest); optional override.
set -euo pipefail

_read_pyproject_version() {
  local pyproject="${1:-pyproject.toml}"
  if [[ ! -f "$pyproject" ]]; then
    return 1
  fi
  grep -E '^version\s*=' "$pyproject" | head -1 | sed -E 's/^version\s*=\s*"([^"]+)".*/\1/'
}

resolve_ghcr_publish_tag() {
  local ref_name="${1:-}"
  local input_tag="${2:-}"
  local pyproject="${3:-pyproject.toml}"

  if [[ "$ref_name" == v* ]]; then
    printf '%s' "${ref_name#v}"
    return 0
  fi
  if [[ "$ref_name" == open-fdd-v* ]]; then
    printf '%s' "${ref_name#open-fdd-v}"
    return 0
  fi

  if [[ -n "$input_tag" && "$input_tag" != "latest" ]]; then
    printf '%s' "${input_tag#v}"
    return 0
  fi

  _read_pyproject_version "$pyproject"
}

ghcr_publish_release_tags_enabled() {
  local ref_name="${1:-}"
  local event_name="${2:-}"

  if [[ "$ref_name" == v* || "$ref_name" == open-fdd-v* ]]; then
    return 0
  fi
  if [[ "$event_name" == "workflow_dispatch" ]]; then
    return 0
  fi
  return 1
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  resolve_ghcr_publish_tag "${1:-}" "${2:-}" "${3:-pyproject.toml}"
fi
