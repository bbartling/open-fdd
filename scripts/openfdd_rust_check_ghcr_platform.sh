#!/usr/bin/env bash
# Verify GHCR Rust edge image exists for host platform (amd64/arm64).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_rust_site_lib.sh
source "$ROOT/scripts/openfdd_rust_site_lib.sh"

IMAGE="${OPENFDD_RUST_GHCR_IMAGE:-ghcr.io/bbartling/openfdd-edge-rust}"
TAG="${OPENFDD_IMAGE_TAG:-nightly}"
PLATFORM="$(openfdd_rust_export_docker_platform)"

echo "Checking GHCR image: ${IMAGE}:${TAG}"
echo "Host platform: ${PLATFORM}"

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker required for manifest inspect" >&2
  exit 1
fi

inspect_manifest() {
  if docker buildx imagetools inspect "${IMAGE}:${TAG}" 2>/dev/null; then
    return 0
  fi
  docker manifest inspect "${IMAGE}:${TAG}" 2>/dev/null
}

if ! inspect_manifest; then
  echo "ERROR: cannot inspect ${IMAGE}:${TAG}" >&2
  echo "Image may not be published yet. Build locally or run GitHub Actions rust-ghcr workflow." >&2
  exit 1
fi

ARCH="${PLATFORM#linux/}"
if docker buildx imagetools inspect "${IMAGE}:${TAG}" 2>/dev/null | grep -qi "$ARCH"; then
  echo "OK: manifest includes ${PLATFORM}"
elif docker manifest inspect "${IMAGE}:${TAG}" 2>/dev/null | grep -qi "$ARCH"; then
  echo "OK: manifest includes ${PLATFORM}"
else
  echo "ERROR: ${IMAGE}:${TAG} does not appear to include ${PLATFORM}" >&2
  if [[ "$ARCH" == "arm64" ]]; then
    echo "Raspberry Pi / ARM64 requires a multi-arch publish from .github/workflows/rust-ghcr.yml" >&2
  fi
  exit 1
fi

echo "GHCR platform check passed."
