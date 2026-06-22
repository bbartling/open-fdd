#!/usr/bin/env bash
# Resolve GHCR publish tag for Rust edge images.
resolve_ghcr_publish_tag() {
  local ref="${1:-}"
  local override="${2:-}"
  if [[ -n "$override" ]]; then
    printf '%s' "$override"
    return 0
  fi
  if [[ -f VERSION ]]; then
    tr -d ' \n\r' <VERSION
    return 0
  fi
  if [[ "$ref" =~ ^v[0-9] ]]; then
    printf '%s' "${ref#v}"
    return 0
  fi
  printf '%s' "latest"
}

ghcr_publish_release_tags_enabled() {
  local ref="${1:-}"
  local event="${2:-}"
  [[ "$event" == "push" && "$ref" =~ ^v[0-9] ]] && return 0
  [[ "$event" == "workflow_dispatch" ]] && return 0
  return 1
}
