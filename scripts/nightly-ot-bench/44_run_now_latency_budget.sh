#!/usr/bin/env bash
# Gate 44 — run-now latency budget (Synthetic-59 scoped watermark).
# Soft-OPEN 370 T3b: export START/END before Python; finite curl/poll timeouts;
# typed completed/partial/no_data only (cancelled/failed ≠ populated latency PASS).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/scripts/nightly-ot-bench/lib.sh"
load_bench_env
BASE="${OPENFDD_API_BASE:-${CENTRAL_BASE:-http://127.0.0.1:8080}}"
BUILDING="${OPENFDD_SYNTH59_BUILDING:-OPENFDD_SYNTHETIC_59_RULE_WEEK_V1}"
BUDGET="${OPENFDD_GATE44_RUN_NOW_BUDGET_SECS:-5}"
CURL_MAX="${OPENFDD_GATE44_CURL_MAX_SECS:-120}"
ART="${ARTIFACT_DIR:-$ROOT/reports/gate44_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$ART"
TOKEN=""
if [[ -n "${OPENFDD_ADMIN_PASSWORD:-}" ]]; then
  TOKEN=$(curl -sf --max-time 10 -X POST "$BASE/api/auth/login" -H 'Content-Type: application/json' \
    -d "{\"username\":\"${OPENFDD_ADMIN_USER:-admin}\",\"password\":\"$OPENFDD_ADMIN_PASSWORD\"}" \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("token") or d.get("access_token") or "")' 2>/dev/null || true)
fi
AUTH=()
[[ -n "$TOKEN" ]] && AUTH=(-H "Authorization: Bearer $TOKEN")
if [[ -z "$TOKEN" ]]; then
  echo "BLOCKED: no auth token for run-now" | tee "$ART/BLOCKED.txt"
  exit 2
fi

start=$(date +%s.%N)
set +e
body=$(curl -sf --max-time "$CURL_MAX" "${AUTH[@]}" -X POST "$BASE/api/afdd/scheduler/run-now" \
  -H 'Content-Type: application/json' \
  -d "{\"building_id\":\"$BUILDING\"}")
curl_rc=$?
set -e
end=$(date +%s.%N)
if [[ "$curl_rc" -ne 0 || -z "$body" ]]; then
  body='{"ok":false,"cycle":{"status":"failed"},"error":"curl_failed_or_empty"}'
fi
elapsed=$(START="$start" END="$end" python3 -c 'import os; print("%.3f" % (float(os.environ["END"]) - float(os.environ["START"])))')
echo "$body" | tee "$ART/run_now.json"
status=$(echo "$body" | python3 -c 'import json,sys; d=json.load(sys.stdin); c=d.get("cycle") or {}; print(c.get("status") or "")')
ok=$(echo "$body" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("1" if d.get("ok") else "0")')
echo "elapsed_s=$elapsed status=$status ok=$ok budget=$BUDGET curl_rc=$curl_rc" | tee "$ART/summary.txt"

python3 - <<PY
import sys
elapsed = float("$elapsed")
budget = float("$BUDGET")
status = "$status"
ok = "$ok"
# Typed terminal outcomes that may qualify latency.
allowed = {"completed", "partial", "no_data"}
if status == "no_data":
    # Empty window short-circuit is an honest fast path.
    if elapsed > budget:
        print(f"FAIL gate 44 no_data but elapsed {elapsed} > budget {budget}", file=sys.stderr)
        sys.exit(1)
    print("PASS gate 44 no_data within budget")
    sys.exit(0)
if status not in allowed:
    print(f"FAIL gate 44 status={status!r} not in {sorted(allowed)} (cancelled/failed cannot qualify populated latency)", file=sys.stderr)
    sys.exit(1)
if ok != "1" and status != "partial":
    print(f"FAIL gate 44 ok={ok} status={status}", file=sys.stderr)
    sys.exit(1)
if elapsed > budget:
    print(f"FAIL gate 44 elapsed {elapsed} > budget {budget}", file=sys.stderr)
    sys.exit(1)
print("PASS gate 44")
PY
