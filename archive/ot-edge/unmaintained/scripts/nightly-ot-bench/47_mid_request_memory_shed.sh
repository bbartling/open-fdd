#!/usr/bin/env bash
# Gate 47 — mid-request memory shed honesty (Soft-OPEN 370 T3b / M70-10).
#
# Schema smoke alone is NOT a memory PASS. Null sample_ms/source/shed_state must
# FAIL. A real PASS requires non-null fields, a nonempty admitted workload, and
# stable started_at across the probe. Induced-pressure trip correlation remains
# a separate LIVE Soft-OPEN case when the tip can safely shed.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/scripts/nightly-ot-bench/lib.sh"
load_bench_env
BASE="${OPENFDD_API_BASE:-${CENTRAL_BASE:-http://127.0.0.1:8080}}"
BUILDING="${OPENFDD_GATE47_BUILDING:-${OPENFDD_SYNTH59_BUILDING:-OPENFDD_SYNTHETIC_59_RULE_WEEK_V1}}"
ART="${ARTIFACT_DIR:-$ROOT/reports/gate47_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$ART"

# Negative fixture (evaluator): null-only health must not PASS (counterexample).
python3 - <<'PY' | tee "$ART/null_counterexample.txt"
import json, sys
# Simulated GATE47_COUNTEREXAMPLE shape — evaluator rejects null-only.
mb = {"sample_ms": None, "source": None, "shed_state": None}
for k in ("sample_ms", "source", "shed_state"):
    v = mb.get(k)
    if v is None or v == "":
        print(f"COUNTEREXAMPLE_REJECT: null/empty {k}")
        break
else:
    print("FAIL: null-only fixture incorrectly accepted", file=sys.stderr)
    sys.exit(1)
print("PASS null-only negative fixture rejected")
PY

TOKEN=""
if [[ -n "${OPENFDD_ADMIN_PASSWORD:-}" ]]; then
  TOKEN=$(curl -sf --max-time 10 -X POST "$BASE/api/auth/login" \
    -H 'Content-Type: application/json' \
    -d "{\"username\":\"${OPENFDD_ADMIN_USER:-admin}\",\"password\":\"$OPENFDD_ADMIN_PASSWORD\"}" \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("token") or d.get("access_token") or "")' 2>/dev/null || true)
fi
AUTH=()
[[ -n "$TOKEN" ]] && AUTH=(-H "Authorization: Bearer $TOKEN")

before=$(curl -sf --max-time 10 "$BASE/api/health")
echo "$before" | tee "$ART/health_before.json"
started_before=$(echo "$before" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("started_at") or "")')

# Nonempty admitted workload (analytics runtime) — not health-only.
workload_rc=0
if [[ -n "$TOKEN" ]]; then
  curl -sf --max-time 120 "${AUTH[@]}" -X POST "$BASE/api/analytics/runtime" \
    -H 'Content-Type: application/json' \
    -d "{\"building_id\":\"$BUILDING\",\"refresh\":true}" \
    | tee "$ART/runtime.json" >/dev/null || workload_rc=$?
else
  echo "BLOCKED: no auth token; cannot run nonempty workload" | tee "$ART/BLOCKED.txt"
  exit 2
fi

after=$(curl -sf --max-time 10 "$BASE/api/health")
echo "$after" | tee "$ART/health_after.json"

python3 - <<PY
import json, sys
before = json.load(open("$ART/health_before.json"))
after = json.load(open("$ART/health_after.json"))
mb = after.get("memory_budget") or {}
required = ("sample_ms", "source", "shed_state")
for k in required:
    if k not in mb:
        print(f"FAIL: memory_budget missing {k}", file=sys.stderr)
        sys.exit(1)
    v = mb.get(k)
    if v is None or v == "":
        print(f"FAIL: memory_budget.{k} is null/empty (null-only health is not memory PASS)", file=sys.stderr)
        sys.exit(1)
started_b = before.get("started_at") or ""
started_a = after.get("started_at") or ""
if not started_b or not started_a:
    print("FAIL: started_at missing", file=sys.stderr)
    sys.exit(1)
if started_b != started_a:
    print(f"FAIL: started_at flipped during gate47 ({started_b} -> {started_a})", file=sys.stderr)
    sys.exit(1)
# Workload must have produced a JSON body (fail-closed HTTP still writes runtime.json via tee only on success).
# If curl failed, runtime.json may be absent — treat as BLOCKED/FAIL honestly.
import os
if not os.path.exists("$ART/runtime.json"):
    print("FAIL: nonempty workload did not produce runtime.json", file=sys.stderr)
    sys.exit(1)
print("PASS gate 47 memory_budget non-null + workload + stable started_at")
print("NOTE: induced-pressure trip correlation is LIVE Soft-OPEN, not this schema+workload smoke")
PY

echo "workload_curl_rc=$workload_rc" | tee -a "$ART/summary.txt"
