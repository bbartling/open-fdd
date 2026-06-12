#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TAG="${OPENFDD_IMAGE_TAG:-local}"
docker build -f "$ROOT/docker/rcx-central/Dockerfile" -t "ghcr.io/bbartling/openfdd-rcx-central:${TAG}" "$ROOT"
echo "Built ghcr.io/bbartling/openfdd-rcx-central:${TAG}"
