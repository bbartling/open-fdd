#!/usr/bin/env bash
# Build Open-FDD edge Docker images (bridge, commission, mcp-rag).
#
#   ./scripts/docker_build.sh              # tag: local
#   OPENFDD_IMAGE_TAG=2026.06.01 ./scripts/docker_build.sh
#   ./scripts/docker_build.sh --save       # also write docker/dist/openfdd-images.tar.gz
#
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

TAG="${OPENFDD_IMAGE_TAG:-local}"
GIT_SHA="$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"
BUILD_TIME="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
DOCKERFILE="${ROOT}/docker/Dockerfile"
BUILD_ARGS=(
  --build-arg "OPENFDD_IMAGE_TAG=${TAG}"
  --build-arg "OPENFDD_BUILD_GIT_SHA=${GIT_SHA}"
  --build-arg "OPENFDD_BUILD_TIME=${BUILD_TIME}"
)
SAVE=false
SKIP_UI=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --save) SAVE=true; shift ;;
    --skip-ui) SKIP_UI=true; shift ;;
    -h|--help)
      echo "Usage: $0 [--save] [--skip-ui]"
      exit 0
      ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [[ "$SKIP_UI" == false && ! -f workspace/api/static/app/index.html ]]; then
  echo "Building dashboard first (workspace/api/static/app missing)…" >&2
  ./scripts/build_operator_dashboard.sh prod
fi

build_one() {
  local target="$1"
  local image="$2"
  echo "==> docker build --target $target -> $image:$TAG"
  docker build -f "$DOCKERFILE" "${BUILD_ARGS[@]}" --target "$target" -t "${image}:${TAG}" .
}

build_one bridge openfdd-bridge
build_one commission openfdd-commission
build_one mcp-rag openfdd-mcp-rag
build_one cloud-exporter openfdd-cloud-exporter

echo ""
echo "Built:"
echo "  openfdd-bridge:${TAG}"
echo "  openfdd-commission:${TAG}"
echo "  openfdd-mcp-rag:${TAG}"
echo "  openfdd-cloud-exporter:${TAG}"

if [[ "$SAVE" == true ]]; then
  mkdir -p docker/dist
  OUT="${ROOT}/docker/dist/openfdd-images-${TAG}.tar.gz"
  echo "==> docker save -> $OUT"
  docker save \
    "openfdd-bridge:${TAG}" \
    "openfdd-commission:${TAG}" \
    "openfdd-mcp-rag:${TAG}" \
    "openfdd-cloud-exporter:${TAG}" \
    | gzip -c > "$OUT"
  echo "Saved image bundle: $OUT"
  echo "Deploy: cd infra/ansible && ./deploy.sh docker --limit <inventory_host> -e openfdd_docker_image_tag=${TAG}"
fi
