#!/usr/bin/env bash
# Poll GHCR until tag is published, then run site update (issue #402 B-01 automation).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

TAG="${NEW_TAG:-3.2.2}"
IMAGE="${OPENFDD_RUST_GHCR_IMAGE:-ghcr.io/bbartling/openfdd-edge-rust}:${TAG}"
INTERVAL="${OPENFDD_GHCR_POLL_SECONDS:-1800}"
MAX_ATTEMPTS="${OPENFDD_GHCR_POLL_MAX:-48}"

echo "Watching GHCR for $IMAGE (every ${INTERVAL}s, max $MAX_ATTEMPTS attempts)"
attempt=0
while (( attempt < MAX_ATTEMPTS )); do
  attempt=$((attempt + 1))
  if docker manifest inspect "$IMAGE" >/dev/null 2>&1; then
    echo "GHCR tag $TAG available — running site update"
    NEW_TAG="$TAG" "$ROOT/scripts/openfdd_rust_site_update.sh"
    OPENFDD_IMAGE_TAG="$TAG" "$ROOT/scripts/openfdd_322_ghcr_validation.sh"
    exit 0
  fi
  echo "Attempt $attempt/$MAX_ATTEMPTS: not published yet"
  sleep "$INTERVAL"
done
echo "ERROR: timed out waiting for $IMAGE" >&2
exit 1
