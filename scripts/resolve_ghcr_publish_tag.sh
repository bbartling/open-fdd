#!/usr/bin/env bash
# Resolve GHCR image tags for publish workflows and diagnostics.
set -euo pipefail

_read_version() {
  local version_file="${1:-VERSION}"
  if [[ -f "$version_file" ]]; then
    tr -d '[:space:]' <"$version_file"
    return 0
  fi
  return 1
}

resolve_ghcr_publish_tag() {
  local ref_name="${1:-}"
  local input_tag="${2:-}"

  if [[ "$ref_name" == "master" || "$ref_name" == "main" ]]; then
    printf '%s' "nightly"
    return 0
  fi
  if [[ "$ref_name" == v* ]]; then
    printf '%s' "${ref_name#v}"
    return 0
  fi
  if [[ "$ref_name" == open-fdd-v* ]]; then
    printf '%s' "${ref_name#open-fdd-v}"
    return 0
  fi
  if [[ -n "$input_tag" && "$input_tag" != "latest" && "$input_tag" != "nightly" ]]; then
    printf '%s' "${input_tag#v}"
    return 0
  fi
  _read_version "VERSION"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  resolve_ghcr_publish_tag "${1:-}" "${2:-}"
fi
