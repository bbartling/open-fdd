#!/usr/bin/env bash
# Image-only GHCR upgrade — pull new tags, recreate containers, keep host workspace/feather.
#
#   OPENFDD_IMAGE_TAG=2026.06.04-edge ./scripts/upgrade_edge_ghcr.sh --limit acme_vm_bbartling
#   OPENFDD_IMAGE_TAG=2026.07.01-edge ./scripts/upgrade_edge_ghcr.sh --limit acme_vm_bbartling
#
# Feather, BACnet tables, rules, and model stay under ~/open-fdd/workspace on the edge host
# (bind mounts). This script never rsyncs workspace/data from bensserver.
#
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}/infra/ansible"

LIMIT=""
EXTRA=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --limit) LIMIT="$2"; shift 2 ;;
    -e) EXTRA+=(-e "$2"); shift 2 ;;
    -h|--help)
      sed -n '2,10p' "$0"
      exit 0
      ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$LIMIT" ]]; then
  echo "Usage: OPENFDD_IMAGE_TAG=<tag> $0 --limit <inventory_host>" >&2
  exit 1
fi

TAG="${OPENFDD_IMAGE_TAG:-}"
if [[ -z "$TAG" || "$TAG" == "local" ]]; then
  echo "Set OPENFDD_IMAGE_TAG to the GHCR tag to pull." >&2
  exit 1
fi

export OPENFDD_IMAGE_TAG="$TAG"
export RUN_POST_CHECK="${RUN_POST_CHECK:-1}"

echo "==> Image-only Docker upgrade (GHCR pull — no workstation file sync)"
./deploy.sh docker --limit "$LIMIT" \
  -e openfdd_docker_sync_workspace_data=false \
  -e openfdd_push_site_pack=false \
  -e openfdd_push_bacnet_config=false \
  "${EXTRA[@]}"

echo "Done. Feather and poll data remain under ~/open-fdd/workspace/data on the edge VM."
