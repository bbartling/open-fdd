#!/usr/bin/env bash
# GHCR pullability report for edge + MCP — use before bench validation runs.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_rust_site_lib.sh
source "$ROOT/scripts/openfdd_rust_site_lib.sh"

EDGE_IMAGE="${OPENFDD_RUST_GHCR_IMAGE:-ghcr.io/bbartling/openfdd-edge-rust}"
MCP_IMAGE="${OPENFDD_MCP_GHCR_IMAGE:-ghcr.io/bbartling/openfdd-mcp}"

read_version() {
  if [[ -f "$ROOT/VERSION" ]]; then
    tr -d '[:space:]' <"$ROOT/VERSION"
  else
    echo "unknown"
  fi
}

REPO_VERSION="$(read_version)"
TAG="${OPENFDD_IMAGE_TAG:-${1:-$REPO_VERSION}}"

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker required" >&2
  exit 1
fi

check_tag() {
  local image="$1" ref="$2"
  if docker manifest inspect "${image}:${ref}" >/dev/null 2>&1; then
    local archs
    archs="$(docker manifest inspect "${image}:${ref}" 2>/dev/null | jq -r '[.manifests[]?.platform.architecture // .architecture] | unique | join(",")' 2>/dev/null || echo "?")"
    printf 'OK\t%s\t%s\t%s\n' "$image" "$ref" "$archs"
    return 0
  fi
  printf 'FAIL\t%s\t%s\tnot pullable (missing tag or orphaned manifest)\n' "$image" "$ref"
  return 1
}

echo "==> Open-FDD GHCR diagnose (requested tag: ${TAG})"
echo "    repo VERSION=${REPO_VERSION}"
echo ""
printf '%s\n' "STATUS	IMAGE	TAG	ARCHS"
fail=0

for ref in "$TAG" "v${TAG}" latest "sha-$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo none)"; do
  check_tag "$EDGE_IMAGE" "$ref" || fail=1
done

for ref in "$TAG" "v${TAG}" latest; do
  check_tag "$MCP_IMAGE" "$ref" || fail=1
done

echo ""
if curl -fsS http://127.0.0.1:8080/api/health >/dev/null 2>&1; then
  echo "==> Running /api/health"
  curl -fsS http://127.0.0.1:8080/api/health | jq '{version, image_tag, image_ref, git_sha_short}'
else
  echo "==> No local edge on :8080 (skip health)"
fi

echo ""
if [[ "$fail" -ne 0 ]]; then
  cat <<EOF
One or more tags failed manifest inspect.

Common causes:
  - Manual GHCR version delete left orphaned tag metadata (re-publish required)
  - Edge master CI never published semver (only sha-*) — run rust-release.yml
  - Package auth: gh auth refresh -h github.com -s read:packages

Republish released line (both edge + MCP, sets :latest):
  gh workflow run "Rust Release (GHCR + GitHub Release)" \\
    --ref release/v3.2.4 -f version=3.2.4 -f prerelease=false

Pin bench site (not sha-*):
  NEW_TAG=3.2.4 ./scripts/openfdd_rust_site_update.sh
EOF
  exit 1
fi

echo "All checked tags are pullable."
