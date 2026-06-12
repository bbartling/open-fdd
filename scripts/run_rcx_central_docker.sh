#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export OPENFDD_IMAGE_TAG="${OPENFDD_IMAGE_TAG:-local}"
exec docker compose -f "$ROOT/docker/rcx-central/docker-compose.yml" up --build "$@"
