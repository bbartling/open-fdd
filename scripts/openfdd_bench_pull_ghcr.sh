#!/usr/bin/env bash
# Pull published Rust edge from GHCR and tag for local compose (no local compile).
#
#   ./scripts/openfdd_bench_pull_ghcr.sh
#   OPENFDD_RUST_GHCR_IMAGE=ghcr.io/bbartling/openfdd-edge-rust:sha-abc123 ./scripts/openfdd_bench_pull_ghcr.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_bench_lib.sh
source "$ROOT/scripts/openfdd_bench_lib.sh"
openfdd_bench_load_env "$ROOT"

GHCR="${OPENFDD_RUST_GHCR_IMAGE:-ghcr.io/bbartling/openfdd-edge-rust:latest}"
LOCAL="${OPENFDD_LOCAL_BRIDGE_IMAGE:-open-fdd-openfdd-bridge:local}"

echo "==> Pulling $GHCR"
docker pull "$GHCR"
echo "==> Tagging as $LOCAL (docker-compose.local.yml)"
docker tag "$GHCR" "$LOCAL"
docker tag "$GHCR" "open-fdd-openfdd-bridge:latest"
echo "OK: bench bridge image ready — no local Rust compile required"
echo "    Start: ./scripts/openfdd_remote_up.sh"
