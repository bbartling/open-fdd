#!/usr/bin/env bash
# Verify GHCR tag is published and edge site reports expected version (issue #402 B-01).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_rust_site_lib.sh
source "$ROOT/scripts/openfdd_rust_site_lib.sh"

TAG="${OPENFDD_IMAGE_TAG:-3.2.2}"
IMAGE="${OPENFDD_RUST_GHCR_IMAGE:-ghcr.io/bbartling/openfdd-edge-rust}:${TAG}"
BASE="${OPENFDD_API_BASE:-http://127.0.0.1:8080}"

echo "==> GHCR manifest inspect: $IMAGE"
docker manifest inspect "$IMAGE" >/dev/null
echo "OK: GHCR tag $TAG published"

echo "==> Edge health + version (expect tag prefix $TAG)"
health="$(curl -fsS "${BASE}/api/health")"
echo "$health" | jq -e '.ok == true' >/dev/null
reported_version="$(echo "$health" | jq -r '.version // .release // empty')"
reported_tag="$(echo "$health" | jq -r '.image_tag // empty')"
if [[ -n "$reported_version" && "$reported_version" != "$TAG" && "$reported_version" != *"$TAG"* ]]; then
  echo "ERROR: /api/health version=$reported_version expected $TAG" >&2
  exit 1
fi
if [[ -n "$reported_tag" && "$reported_tag" != "$TAG" && "$reported_tag" != "latest" ]]; then
  echo "ERROR: /api/health image_tag=$reported_tag expected $TAG" >&2
  exit 1
fi
echo "OK: health version=${reported_version:-unknown} image_tag=${reported_tag:-unknown}"

"$ROOT/scripts/openfdd_rust_edge_validate.sh"
echo "GHCR validation complete for tag $TAG"
