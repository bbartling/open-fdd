#!/usr/bin/env bash
# Full edge upgrade from bensserver — UI static bundle + GHCR images + insurance check.
#
# Why both steps:
#   - Bridge serves workspace/api/static/app/ from the bind mount BEFORE image-baked assets.
#   - Image-only upgrade (upgrade_edge_ghcr.sh) leaves an old React bundle on disk.
#
#   ./scripts/build_operator_dashboard.sh prod   # or build_and_test.sh
#   OPENFDD_IMAGE_TAG=2026.06.08-edge ./scripts/upgrade_edge_full.sh --limit acme_vm_bbartling
#
# Skips UI rebuild when workspace/api/static/app/index.html already exists (pass --skip-ui-build).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

LIMIT=""
SKIP_UI_BUILD=0
SKIP_UI_DEPLOY=0
EXTRA=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --limit) LIMIT="$2"; shift 2 ;;
    --skip-ui-build) SKIP_UI_BUILD=1; shift ;;
    --skip-ui-deploy) SKIP_UI_DEPLOY=1; shift ;;
    -e) EXTRA+=(-e "$2"); shift 2 ;;
    -h|--help)
      sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

[[ -n "$LIMIT" ]] || { echo "Usage: OPENFDD_IMAGE_TAG=<tag> $0 --limit <inventory_host>" >&2; exit 1; }

TAG="${OPENFDD_IMAGE_TAG:-}"
if [[ -z "$TAG" || "$TAG" == "local" ]]; then
  echo "Set OPENFDD_IMAGE_TAG to the GHCR tag published by CI (e.g. 3.0.32 or latest)." >&2
  exit 1
fi
# shellcheck source=scripts/openfdd_normalize_image_tag.sh
source "${ROOT}/scripts/openfdd_normalize_image_tag.sh"
TAG="$(normalize_openfdd_image_tag "$TAG")"
export OPENFDD_IMAGE_TAG="$TAG"

LOCAL_ASSET=""
if [[ -f workspace/api/static/app/index.html ]]; then
  LOCAL_ASSET="$(grep -oE 'index-[^"]+\.js' workspace/api/static/app/index.html | head -1 || true)"
fi

echo "==> Full edge upgrade → ${LIMIT} (image tag ${TAG})"
[[ -n "$LOCAL_ASSET" ]] && echo "    Local UI bundle: ${LOCAL_ASSET}"

if [[ "$SKIP_UI_BUILD" == "0" ]]; then
  echo "==> Build React dashboard → workspace/api/static/app/"
  ./scripts/build_operator_dashboard.sh prod
  LOCAL_ASSET="$(grep -oE 'index-[^"]+\.js' workspace/api/static/app/index.html | head -1 || true)"
  echo "    Built: ${LOCAL_ASSET}"
else
  [[ -f workspace/api/static/app/index.html ]] || {
    echo "Missing workspace/api/static/app/index.html — run without --skip-ui-build" >&2
    exit 1
  }
fi

if [[ "$SKIP_UI_DEPLOY" == "0" ]]; then
  echo "==> Sync UI static bundle to edge (workspace/api/static/app/ bind mount)"
  "${ROOT}/scripts/edge_sync_ui_static.sh" --limit "$LIMIT"
else
  echo "==> Skipping UI deploy (--skip-ui-deploy)"
fi

echo "==> Pull GHCR images and recreate containers (workspace data preserved)"
OPENFDD_IMAGE_TAG="$TAG" RUN_POST_CHECK=0 "${ROOT}/scripts/upgrade_edge_ghcr.sh" --limit "$LIMIT" "${EXTRA[@]}"

echo "==> Post-deploy insurance check"
cd "${ROOT}/infra/ansible"
./scripts/post_deploy_check.sh --limit "$LIMIT" --full

echo ""
echo "OK — full upgrade complete for ${LIMIT}."
echo "Browser: open http://<edge-ip>/ and confirm bundle ${LOCAL_ASSET:-?} (not an older index-*.js)."
echo "Host stats page should show container image tag ${TAG} when bridge reports revisions."
