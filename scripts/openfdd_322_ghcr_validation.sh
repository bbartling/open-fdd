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

echo "==> Edge health + version"
curl -fsS "${BASE}/api/health" | jq -e '.ok == true'
curl -fsS "${BASE}/api/health" | jq -r '.version // .release // "unknown"'

"$ROOT/scripts/openfdd_rust_edge_validate.sh"
echo "GHCR validation complete for tag $TAG"
