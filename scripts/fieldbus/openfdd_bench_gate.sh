#!/usr/bin/env bash
# Open-FDD bench gate — smoke + full bench driver + per-feature BACnet PCAP validation.
#
# Runs the validation suite the way Open-FDD would use the sidecar in production:
#   1. scripts/smoke_test.sh           (fast REST fail gate)
#   2. scripts/bench_test.sh           (BACnet matrix + Modbus + Haystack + PCAP per phase)
#
# Usage:
#   OPENFDD_FIELDBUS_API_KEY=... scripts/openfdd_bench_gate.sh
#   BENCH_MINUTES=30 scripts/openfdd_bench_gate.sh   # half-hour soak inside bench_test
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/bench_lib.sh
source "$ROOT/scripts/bench_lib.sh"

bench_load_env "$ROOT"
bench_require_tools

echo "== Open-FDD bench gate =="
echo "base=$BENCH_BASE artifacts=${BENCH_ARTIFACTS:-$ROOT/artifacts}"

echo
echo "== Phase 1: smoke_test.sh =="
"$ROOT/scripts/smoke_test.sh"

echo
echo "== Phase 2: bench_test.sh (BACnet PCAP + Modbus + Haystack) =="
export BENCH_PCAP="${BENCH_PCAP:-1}"
export BENCH_MINUTES="${BENCH_MINUTES:-0}"
"$ROOT/scripts/bench_test.sh"

echo
echo "== BENCH GATE PASSED =="
