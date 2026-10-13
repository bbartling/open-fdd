#!/usr/bin/env bash
# Wave-X host-run of openfdd-central against compose Timescale (no docker-build).
# Soft-OPEN ≠ FQ. mintbench: prefer GHCR tip instead.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
export OPENFDD_HISTORIAN="${OPENFDD_HISTORIAN:-timescale}"
export OPENFDD_FDD_ENGINE="${OPENFDD_FDD_ENGINE:-postgres-sql}"
export OPENFDD_DATABASE_URL="${OPENFDD_DATABASE_URL:-postgresql://openfdd:openfdd_dev_only@127.0.0.1:5432/openfdd}"
export OPENFDD_SQL_ROOT="${OPENFDD_SQL_ROOT:-$ROOT/sql/fdd}"
export OPENFDD_JWT_SECRET="${OPENFDD_JWT_SECRET:-wave-x-dev-only-change-me}"
export OPENFDD_ADMIN_PASSWORD="${OPENFDD_ADMIN_PASSWORD:-admin}"
export OPENFDD_MQTT_ENABLED="${OPENFDD_MQTT_ENABLED:-0}"
export OPENFDD_WORKSPACE="${OPENFDD_WORKSPACE:-$ROOT/workspace}"
export OPENFDD_STORAGE_URL="${OPENFDD_STORAGE_URL:-file://$ROOT/workspace/openfdd-compat-retired}"
export OPENFDD_GIT_SHA="${OPENFDD_GIT_SHA:-$(git rev-parse --short HEAD)}"
export CARGO_BUILD_JOBS="${CARGO_BUILD_JOBS:-2}"
exec cargo run -p openfdd-central --release -- "$@"
