#!/usr/bin/env bash
# Verify GHCR Open-FDD images publish a manifest for this host CPU (or a chosen platform).
#
#   ./scripts/openfdd_check_ghcr_platform.sh
#   ./scripts/openfdd_check_ghcr_platform.sh --platform linux/amd64
#   OPENFDD_IMAGE_TAG=3.1.6 ./scripts/openfdd_check_ghcr_platform.sh
#   OPENFDD_DOCKER_PLATFORM=linux/arm64 ./scripts/openfdd_check_ghcr_platform.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=openfdd_site_lib.sh
source "${SCRIPT_DIR}/openfdd_site_lib.sh"

TAG="${OPENFDD_IMAGE_TAG:-latest}"
OWNER="${OPENFDD_GHCR_OWNER:-bbartling}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --platform) OPENFDD_DOCKER_PLATFORM="$2"; shift 2 ;;
    --image-tag) OPENFDD_IMAGE_TAG="$2"; TAG="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

PLATFORM="$(openfdd_export_docker_platform)"
ARCH="$(openfdd_platform_arch "$PLATFORM")"
HOST_ARCH="$(uname -m)"

IMAGES=(
  openfdd-bridge
  openfdd-commission
  openfdd-mcp-rag
)

echo "Host CPU: ${HOST_ARCH} → checking GHCR manifests for ${PLATFORM} (tag=${TAG})"

missing=()
for img in "${IMAGES[@]}"; do
  ref="ghcr.io/${OWNER}/${img}:${TAG}"
  if ! docker manifest inspect "$ref" >/dev/null 2>&1; then
    echo "ERROR: cannot inspect manifest: $ref" >&2
    missing+=("$ref (manifest missing)")
    continue
  fi
  if ! docker manifest inspect "$ref" 2>/dev/null | grep -q "\"architecture\": \"${ARCH}\""; then
    missing+=("$ref (no ${ARCH})")
  else
    echo "OK  $ref → ${ARCH}"
  fi
done

if [[ ${#missing[@]} -gt 0 ]]; then
  echo "" >&2
  echo "Open-FDD GHCR images are not published for ${PLATFORM} (tag=${TAG})." >&2
  echo "This host: ${HOST_ARCH} / ${PLATFORM}" >&2
  echo "" >&2
  for m in "${missing[@]}"; do
    echo "  ✗ $m" >&2
  done
  echo "" >&2
  if [[ "$ARCH" == "arm64" ]]; then
    cat >&2 <<'EOF'
Raspberry Pi / ARM64 options:

  1. RECOMMENDED — Use a tag with native ARM64 images (3.1.6+ multi-arch publish).
     Re-run: bash /tmp/openfdd_edge_bootstrap.sh --start

  2. WORKAROUND — QEMU emulation (slow; lab only):
     sudo apt install -y qemu-user-static binfmt-support
     docker run --privileged --rm tonistiigi/binfmt --install amd64
     cd ~/open-fdd
     OPENFDD_DOCKER_PLATFORM=linux/amd64 ./scripts/openfdd_site_update.sh

  3. BUILD ON PI — clone repo and: ./scripts/docker_build.sh (needs ~30–60 min on Pi 5)

Docs: https://bbartling.github.io/open-fdd/quick-start/raspberry-pi-edge/
EOF
  elif [[ "$ARCH" == "amd64" && "$HOST_ARCH" =~ ^(aarch64|arm64)$ ]]; then
    cat >&2 <<'EOF'
You requested linux/amd64 on an ARM64 host (QEMU emulation). Ensure binfmt is installed:
  docker run --privileged --rm tonistiigi/binfmt --install amd64
EOF
  fi
  exit 1
fi

echo "All edge images support ${PLATFORM} (tag=${TAG})."
