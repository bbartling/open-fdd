#!/usr/bin/env bash
# Half-hour bench 5007 smoke — PyArrow vs DataFusion SQL + health probes + RCx DOCX.
#
# Cursor/agents: NEVER wait on this process. Poll status only:
#   ./scripts/smoke_bench_5007_half_hour_status.sh
#
#   ./scripts/smoke_bench_5007_half_hour.sh
#   ./scripts/smoke_bench_5007_half_hour.sh --with-parity   # also run site parity pre-check
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export OPENFDD_SMOKE_BENCH_ONLY=1
export OPENFDD_SMOKE_HEALTH_PROBES=1
export OPENFDD_SMOKE_RCX_REPORT=1

EXTRA=(--bench-only)
while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-parity) EXTRA+=(--with-parity); shift ;;
    -h|--help)
      sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) EXTRA+=("$1"); shift ;;
  esac
done

exec "${ROOT}/scripts/run_paired_fdd_smoke_isolated.sh" --short "${EXTRA[@]}"
