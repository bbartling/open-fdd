#!/usr/bin/env bash
# Soft-OPEN 370 T1h/T6a entrypoint — portable local memory/ingest bench.
# Usage:
#   ./scripts/ops/run_local_memory_ingest_bench.sh mintbench-3g
#   ./scripts/ops/run_local_memory_ingest_bench.sh bench32-4g --central-base http://127.0.0.1:8080
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PROFILE="${1:-}"
if [[ -z "$PROFILE" ]]; then
  echo "usage: $0 <profile> [extra args for local_memory_ingest_bench.py]" >&2
  echo "profiles: bench32-4g bench32-8g mintbench-3g mintbench-4g-central" >&2
  exit 2
fi
shift || true
exec python3 "$ROOT/scripts/ops/local_memory_ingest_bench.py" --profile "$PROFILE" "$@"
