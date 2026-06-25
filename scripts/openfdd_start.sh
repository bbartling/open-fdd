#!/usr/bin/env bash
# One command: auth (auto-rotate if needed) + dashboard + Docker + smoke.
# Does NOT run local Docker Rust --build (use openfdd_remote_up.sh for remote dial-in).
#
#   ./scripts/openfdd_start.sh
#   OPENFDD_ALLOW_LOCAL_BUILD=1 ./scripts/openfdd_start.sh --build   # rare; needs 12GB+ free
#
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ " $* " == *" --build "* ]]; then
  echo "WARN: --build compiles Rust on this bench — prefer ./scripts/openfdd_remote_up.sh or ./scripts/openfdd_bench_pull_ghcr.sh" >&2
fi
exec "$ROOT/scripts/openfdd_inspection_build.sh" --smoke --skip-rust "$@"
