#!/usr/bin/env bash
# Bootstrap an edge host from published GHCR images (no local docker save/tar).
#
#   OPENFDD_IMAGE_TAG=2026.06.04-edge ./scripts/bootstrap_edge_ghcr.sh --limit acme_vm_bbartling
#
# Prerequisites on control machine (bensserver):
#   - Built UI: workspace/api/static/app/index.html (run build_and_test.sh once)
#   - infra/ansible/secrets/<host>.env.local with SSHPASS (or export SSHPASS)
#   - host_vars for the inventory host (openfdd_docker_pull_from_ghcr, site_id, BACnet bind, …)
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
      sed -n '2,12p' "$0"
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
  echo "Set OPENFDD_IMAGE_TAG to a tag published by GitHub Actions → Publish Docker addons." >&2
  exit 1
fi

if [[ ! -f "${ROOT}/workspace/api/static/app/index.html" ]]; then
  echo "Building operator dashboard…" >&2
  "${ROOT}/scripts/build_operator_dashboard.sh" prod
fi

export OPENFDD_IMAGE_TAG="$TAG"
export RUN_POST_CHECK="${RUN_POST_CHECK:-1}"

echo "==> Docker stack (GHCR pull + workspace sync)"
./deploy.sh docker --limit "$LIMIT" -e openfdd_docker_ollama=false "${EXTRA[@]}"

echo "==> Caddy (host :80 → bridge; after compose is up)"
./deploy.sh caddy --limit "$LIMIT" "${EXTRA[@]}"

echo '==> Host Ollama + MCP when enabled in host_vars'
./deploy.sh ai --limit "$LIMIT" "${EXTRA[@]}" || true

echo "==> Operational sync (TTL, probes, feather check)"
./deploy.sh ops --limit "$LIMIT" "${EXTRA[@]}"

echo "Done. Open http://<edge-tailscale-ip>/ and run post-deploy checks if needed."
