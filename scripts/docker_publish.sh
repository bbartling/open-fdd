#!/usr/bin/env bash
# Publish Open-FDD addon images to GHCR (supervisor/apps layer).
#
#   GITHUB_TOKEN=ghp_… ./scripts/docker_publish.sh
#   OPENFDD_IMAGE_TAG=2026.06.01 ./scripts/docker_publish.sh
#   PUBLISH_LATEST_ONLY=1 OPENFDD_IMAGE_TAG=latest ./scripts/docker_publish.sh
#   PUBLISH_LATEST=1 OPENFDD_IMAGE_TAG=2026.06.01-edge ./scripts/docker_publish.sh  # legacy dated tag
#
# Requires: docker login ghcr.io, images already built (./scripts/docker_build.sh)
#
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

TAG="${OPENFDD_IMAGE_TAG:-local}"
REGISTRY="${OPENFDD_REGISTRY:-ghcr.io}"
ORG="${OPENFDD_REGISTRY_ORG:-bbartling}"

if [[ "$TAG" == "local" ]]; then
  echo "Set OPENFDD_IMAGE_TAG to a release version before publishing (not 'local')." >&2
  exit 1
fi

IMAGES=(openfdd-bridge openfdd-commission openfdd-mcp-rag)

publish_tag="${TAG}"
if [[ "${PUBLISH_LATEST_ONLY:-}" == "1" ]]; then
  publish_tag="latest"
fi

for img in "${IMAGES[@]}"; do
  src="${img}:${TAG}"
  dst="${REGISTRY}/${ORG}/${img}:${publish_tag}"
  echo "==> tag $src -> $dst"
  docker tag "$src" "$dst"
  echo "==> push $dst"
  docker push "$dst"
  if [[ "${PUBLISH_LATEST:-}" == "1" && "$publish_tag" != "latest" && "$TAG" != "latest" ]]; then
    latest="${REGISTRY}/${ORG}/${img}:latest"
    docker tag "$src" "$latest"
    docker push "$latest"
  fi
done

echo ""
echo "Published ${#IMAGES[@]} images under ${REGISTRY}/${ORG}/ with tag ${publish_tag}"
if [[ "${PUBLISH_LATEST_ONLY:-}" == "1" ]]; then
  echo "Tip: ./scripts/ghcr_prune_packages.sh --delete-retired --keep 3"
fi
echo "Edge: OPENFDD_IMAGE_TAG=${TAG} ./scripts/docker_build.sh --save  # or compose pull when registry deploy lands"
