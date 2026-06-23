#!/usr/bin/env bash
# Deprecated wrapper — use scripts/smoke_live_fdd_validation.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo "NOTE: bench_5007_long_smoke.sh is deprecated; use scripts/smoke_live_fdd_validation.sh" >&2
export OPENFDD_SMOKE_DEVICE_INSTANCE="${OPENFDD_SMOKE_DEVICE_INSTANCE:-5007}"
export BENCH_SMOKE_HOURS="${BENCH_SMOKE_HOURS:-${OPENFDD_SMOKE_DURATION_HOURS:-6}}"
export BENCH_SMOKE_INTERVAL_SEC="${BENCH_SMOKE_INTERVAL_SEC:-${OPENFDD_SMOKE_INTERVAL_SECONDS:-300}}"
export BENCH_SMOKE_LIVE_FDD="${BENCH_SMOKE_LIVE_FDD:-${OPENFDD_SMOKE_LIVE_FDD:-0}}"
export BENCH_SMOKE_SIMULATE="${BENCH_SMOKE_SIMULATE:-${OPENFDD_SMOKE_SIMULATE:-0}}"
export BENCH_SMOKE_SHORT_FDD="${BENCH_SMOKE_SHORT_FDD:-0}"
exec "$ROOT/scripts/smoke_live_fdd_validation.sh" "$@"
