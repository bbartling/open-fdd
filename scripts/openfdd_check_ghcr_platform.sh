#!/usr/bin/env bash
# Verify GHCR Open-FDD images publish a manifest for this host CPU.
#
#   ./scripts/openfdd_check_ghcr_platform.sh
#   OPENFDD_IMAGE_TAG=3.1.6 ./scripts/openfdd_check_ghcr_platform.sh
set -euo pipefail

TAG="${OPENFDD_IMAGE_TAG:-latest}"
OWNER="${OPENFDD_GHCR_OWNER:-bbartling}"

_detect_platform() {
  case "$(uname -m)" in
    aarch64|arm64) echo "linux/arm64" ;;
    x86_64|amd64) echo "linux/amd64" ;;
    *) echo "linux/$(uname -m)" ;;
  esac
}

PLATFORM="$(_detect_platform)"
ARCH="${PLATFORM#linux/}"

IMAGES=(
  openfdd-bridge
  openfdd-commission
  openfdd-mcp-rag
)

missing=()
for img in "${IMAGES[@]}"; do
  ref="ghcr.io/${OWNER}/${img}:${TAG}"
  if ! docker manifest inspect "$ref" >/dev/null 2>&1; then
    echo "ERROR: cannot inspect manifest: $ref" >&2
    missing+=("$ref (manifest missing)")
    continue
  fi
  if ! docker manifest inspect "$ref" 2>/dev/null | grep -q "\"architecture\": \"${ARCH}\""; then
    missing+=("$ref (no ${ARCH} — Pi needs linux/arm64)")
  else
    echo "OK  $ref → ${ARCH}"
  fi
done

if [[ ${#missing[@]} -gt 0 ]]; then
  echo "" >&2
  echo "Open-FDD GHCR images are not published for ${PLATFORM} (tag=${TAG})." >&2
  echo "This host: $(uname -m) / ${PLATFORM}" >&2
  echo "" >&2
  for m in "${missing[@]}"; do
    echo "  ✗ $m" >&2
  done
  echo "" >&2
  if [[ "$ARCH" == "arm64" ]]; then
    cat >&2 <<'EOF'
Raspberry Pi / ARM64 options:

  1. RECOMMENDED — Wait for native ARM64 images (after next Open-FDD release publish).
     Re-run: bash /tmp/openfdd_edge_bootstrap.sh --start

  2. WORKAROUND — QEMU emulation (slow; lab only):
     sudo apt install -y qemu-user-static binfmt-support
     docker run --privileged --rm tonistiigi/binfmt --install amd64
     cd ~/open-fdd
     DOCKER_DEFAULT_PLATFORM=linux/amd64 docker compose pull
     DOCKER_DEFAULT_PLATFORM=linux/amd64 docker compose up -d

  3. BUILD ON PI — clone repo and: ./scripts/docker_build.sh (needs ~30–60 min on Pi 5)

Docs: https://bbartling.github.io/open-fdd/quick-start/raspberry-pi-edge/
EOF
  fi
  exit 1
fi

echo "All edge images support ${PLATFORM} (tag=${TAG})."
