#!/usr/bin/env bash
# Run docker compose in the official volttron-docker checkout (PNNL/VOLTTRON upstream).
# Open-FDD never modifies that tree; clone/update it with: ./scripts/bootstrap.sh --volttron-docker
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VOLTTRON_DOCKER_DIR="${OFDD_VOLTTRON_DOCKER_DIR:-$HOME/volttron-docker}"
if [[ ! -d "$VOLTTRON_DOCKER_DIR" ]]; then
  echo "[FAIL] Missing volttron-docker directory: $VOLTTRON_DOCKER_DIR" >&2
  echo "       Clone it from this repo: (cd \"$ROOT\" && ./scripts/bootstrap.sh --volttron-docker)" >&2
  exit 1
fi
if [[ ! -f "$VOLTTRON_DOCKER_DIR/docker-compose.yml" ]]; then
  echo "[FAIL] No docker-compose.yml in $VOLTTRON_DOCKER_DIR" >&2
  exit 1
fi
echo "[INFO] Open-FDD repo: $ROOT"
echo "[INFO] Upstream volttron-docker (read-only use): $VOLTTRON_DOCKER_DIR"
cd "$VOLTTRON_DOCKER_DIR"
exec docker compose "$@"
