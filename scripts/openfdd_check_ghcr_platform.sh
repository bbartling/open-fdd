#!/usr/bin/env bash
# LEGACY: local source-checkout platform check.
# For GHCR Rust edge use: scripts/openfdd_rust_check_ghcr_platform.sh
set -euo pipefail
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64|amd64) PLATFORM="linux/amd64" ;;
  aarch64|arm64) PLATFORM="linux/arm64" ;;
  *) PLATFORM="unknown" ;;
esac
echo "host_arch=${ARCH}"
echo "docker_platform=${PLATFORM}"
echo "This Rust-only baseline builds locally by Dockerfile. GHCR publishing can be added later."
