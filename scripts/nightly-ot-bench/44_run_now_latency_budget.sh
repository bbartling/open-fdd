#!/usr/bin/env bash
# Gate 44 — run-now latency budget (Synthetic-59 scoped watermark).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/scripts/nightly-ot-bench/lib.sh"
load_bench_env
BASE="${OPENFDD_API_BASE:-${CENTRAL_BASE:-http://127.0.0.1:8080}}"
BUILDING="${OPENFDD_SYNTH59_BUILDING:-OPENFDD_SYNTHETIC_59_RULE_WEEK_V1}"
BUDGET="${OPENFDD_GATE44_RUN_NOW_BUDGET_SECS:-5}"
ART="${ARTIFACT_DIR:-$ROOT/reports/gate44_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$ART"
TOKEN=""
if [[ -n "${OPENFDD_ADMIN_PASSWORD:-}" ]]; then
  TOKEN=$(curl -sf -X POST "$BASE/api/auth/login" -H 'Content-Type: application/json' \
    -d "{\"username\":\"${OPENFDD_ADMIN_USER:-admin}\",\"password\":\"$OPENFDD_ADMIN_PASSWORD\"}" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin).get("token") or json.load(sys.stdin).get("access_token") or "")' 2>/dev/null || true)
fi
AUTH=()
[[ -n "$TOKEN" ]] && AUTH=(-H "Authorization: Bearer $TOKEN")
start=$(date +%s.%N)
body=$(curl -sf "${AUTH[@]}" -X POST "$BASE/api/afdd/scheduler/run-now" \
  -H 'Content-Type: application/json' \
  -d "{\"building_id\":\"$BUILDING\"}" || echo '{"ok":false}')
end=$(date +%s.%N)
elapsed=$(python3 - <<PY
import os
print(f"{float(os.environ['END'])-float(os.environ['START']):.3f}")
PY
START="$start" END="$end")
echo "$body" | tee "$ART/run_now.json"
status=$(echo "$body" | python3 -c 'import json,sys; d=json.load(sys.stdin); c=d.get("cycle") or {}; print(c.get("status",""))')
ok=$(echo "$body" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("1" if d.get("ok") else "0")')
echo "elapsed_s=$elapsed status=$status ok=$ok budget=$BUDGET" | tee "$ART/summary.txt"
if python3 - <<PY
import sys
elapsed=float("$elapsed")
budget=float("$BUDGET")
status="$status"
ok="$ok"
if elapsed > budget:
    sys.exit(1)
if status in ("cancelled",) or ok != "1":
    if status == "no_data":
        sys.exit(0)
    sys.exit(1)
PY
then
  echo "PASS gate 44"
else
  echo "FAIL gate 44 elapsed=$elapsed status=$status" >&2
  exit 1
fi
