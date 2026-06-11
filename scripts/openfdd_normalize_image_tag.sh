#!/usr/bin/env bash
# GHCR SemVer tags omit the leading "v" (workflow publishes 3.0.32, not v3.0.32).
# Normalize OPENFDD_IMAGE_TAG for docker compose / validation probes.
normalize_openfdd_image_tag() {
  local raw="${1:-}"
  raw="${raw#v}"
  printf '%s' "$raw"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  normalize_openfdd_image_tag "${OPENFDD_IMAGE_TAG:-}"
fi
