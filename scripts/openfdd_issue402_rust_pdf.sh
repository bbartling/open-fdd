#!/usr/bin/env bash
# Generate issue #402 findings PDF via Rust reports API (no Python).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_auth_lib.sh
source "$ROOT/scripts/openfdd_auth_lib.sh"

BASE="${OPENFDD_API_BASE:-http://127.0.0.1:8080}"
AUTH="$ROOT/workspace/auth.env.local"
REPORT_ID="${OPENFDD_ISSUE402_REPORT_ID:-rpt-issue402-322-bench}"
OUT_DIR="${OPENFDD_ISSUE402_OUT_DIR:-$ROOT/workspace/reports/$REPORT_ID}"
mkdir -p "$OUT_DIR"

TOKEN="$(openfdd_auth_login_token "$BASE" "$AUTH" integrator)"

draft="$(curl -fsS -X POST "${BASE}/api/reports/draft" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg id "$REPORT_ID" --arg title "3.2.2 field testbench findings" \
    '{report_id:$id,title:$title,kind:"rcx",sections:["executive_summary","validation","drivers","security"]}')")"
echo "$draft" | jq -e '.ok == true' >/dev/null
rid="$(echo "$draft" | jq -r '.report_id // .id // empty')"
[[ -n "$rid" ]] || rid="$REPORT_ID"

curl -fsS -X POST "${BASE}/api/reports/${rid}/render/pdf" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{}' | jq -e '.ok == true' >/dev/null

curl -fsS "${BASE}/api/reports/${rid}/download.pdf" \
  -H "Authorization: Bearer ${TOKEN}" \
  -o "$OUT_DIR/findings.pdf"

if [[ -s "$OUT_DIR/findings.pdf" ]]; then
  echo "OK: Rust PDF written to $OUT_DIR/findings.pdf ($(wc -c <"$OUT_DIR/findings.pdf") bytes)"
else
  echo "ERROR: PDF empty or missing" >&2
  exit 1
fi
