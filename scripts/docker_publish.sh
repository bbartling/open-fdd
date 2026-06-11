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
# GHCR may intermittently return "unknown blob" on large layer uploads (commission image).
# Each push is retried with manifest verification — see open-fdd#260.
#
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

TAG="${OPENFDD_IMAGE_TAG:-local}"
REGISTRY="${OPENFDD_REGISTRY:-ghcr.io}"
ORG="${OPENFDD_REGISTRY_ORG:-bbartling}"
PUSH_RETRY_MAX="${DOCKER_PUSH_RETRY_MAX:-5}"
PUSH_RETRY_BASE_S="${DOCKER_PUSH_RETRY_BASE_S:-8}"

if [[ "$TAG" == "local" ]]; then
  echo "Set OPENFDD_IMAGE_TAG to a release version before publishing (not 'local')." >&2
  exit 1
fi

IMAGES=(openfdd-bridge openfdd-commission openfdd-mcp-rag)

publish_tag="${TAG}"
if [[ "${PUBLISH_LATEST_ONLY:-}" == "1" ]]; then
  publish_tag="latest"
fi

verify_manifest() {
  local ref="$1"
  if docker manifest inspect "$ref" >/dev/null 2>&1; then
    return 0
  fi
  if command -v crane >/dev/null 2>&1 && crane manifest "$ref" >/dev/null 2>&1; then
    return 0
  fi
  return 1
}

push_with_retry() {
  local dst="$1"
  local attempt=1
  local delay="$PUSH_RETRY_BASE_S"
  while [[ "$attempt" -le "$PUSH_RETRY_MAX" ]]; do
    echo "==> push $dst (attempt ${attempt}/${PUSH_RETRY_MAX})"
    if docker push "$dst"; then
      if verify_manifest "$dst"; then
        echo "    OK manifest verified for $dst"
        return 0
      fi
      echo "    WARN: push succeeded but manifest inspect failed — retrying" >&2
    else
      echo "    WARN: docker push failed (exit $?) — retrying" >&2
    fi
    if [[ "$attempt" -lt "$PUSH_RETRY_MAX" ]]; then
      echo "    sleeping ${delay}s before retry…"
      sleep "$delay"
      delay=$((delay + PUSH_RETRY_BASE_S))
    fi
    attempt=$((attempt + 1))
  done
  echo "FAIL: could not push and verify $dst after ${PUSH_RETRY_MAX} attempts" >&2
  return 1
}

FAILED=0
for img in "${IMAGES[@]}"; do
  src="${img}:${TAG}"
  dst="${REGISTRY}/${ORG}/${img}:${publish_tag}"
  echo "==> tag $src -> $dst"
  docker tag "$src" "$dst"
  if ! push_with_retry "$dst"; then
    FAILED=$((FAILED + 1))
  fi
  if [[ "${PUBLISH_LATEST:-}" == "1" && "$publish_tag" != "latest" && "$TAG" != "latest" ]]; then
    latest="${REGISTRY}/${ORG}/${img}:latest"
    docker tag "$src" "$latest"
    if ! push_with_retry "$latest"; then
      FAILED=$((FAILED + 1))
    fi
  fi
done

echo ""
if [[ "$FAILED" -gt 0 ]]; then
  echo "Published with ${FAILED} failure(s) — re-run workflow or: OPENFDD_IMAGE_TAG=${TAG} ./scripts/docker_publish.sh" >&2
  exit 1
fi
echo "Published ${#IMAGES[@]} images under ${REGISTRY}/${ORG}/ with tag ${publish_tag}"
if [[ "${PUBLISH_LATEST_ONLY:-}" == "1" ]]; then
  echo "Tip: ./scripts/ghcr_prune_packages.sh --delete-retired --keep 3"
fi
echo "Edge: OPENFDD_IMAGE_TAG=${TAG} ./scripts/docker_build.sh --save  # or compose pull when registry deploy lands"
