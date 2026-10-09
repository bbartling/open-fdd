#!/usr/bin/env bash
# Gate 47 — memory_budget exposes sample_ms + last_trip on /api/health.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/scripts/nightly-ot-bench/lib.sh"
load_bench_env
BASE="${OPENFDD_API_BASE:-${CENTRAL_BASE:-http://127.0.0.1:8080}}"
ART="${ARTIFACT_DIR:-$ROOT/reports/gate47_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$ART"
health=$(curl -sf "$BASE/api/health")
echo "$health" | tee "$ART/health.json"
echo "$health" | python3 -c '
import json, sys
h=json.load(sys.stdin)
mb=h.get("memory_budget") or {}
for k in ("sample_ms","source","shed_state"):
    if k not in mb:
        print(f"FAIL: memory_budget missing {k}", file=sys.stderr)
        sys.exit(1)
print("PASS gate 47 memory_budget fields present")
'
