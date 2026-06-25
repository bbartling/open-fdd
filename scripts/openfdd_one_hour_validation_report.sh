#!/usr/bin/env bash
# One-hour local validation + PDF report orchestration.
#
#   ./scripts/openfdd_one_hour_validation_report.sh
#
# Quick wiring test (not acceptance):
#   OPENFDD_VALIDATION_QUICK_MINUTES=3 ./scripts/openfdd_one_hour_validation_report.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_auth_lib.sh
source "$ROOT/scripts/openfdd_auth_lib.sh"

BASE="${OPENFDD_API_BASE:-http://127.0.0.1:8080}"
AUTH="${OPENFDD_AUTH_ENV:-$ROOT/workspace/auth.env.local}"
RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
ORCH_DIR="${OPENFDD_ONE_HOUR_ARTIFACT:-$ROOT/workspace/logs/one_hour_validation_${RUN_TS}}"
QUICK_MIN="${OPENFDD_VALIDATION_QUICK_MINUTES:-0}"

mkdir -p "$ORCH_DIR"
exec > >(tee -a "$ORCH_DIR/orchestrator.log") 2>&1

echo "==> Open-FDD one-hour validation orchestration"
echo "    artifact=$ORCH_DIR"

VALIDATION_PROFILE="${OPENFDD_VALIDATION_PROFILE:-$ROOT/workspace/smoke-profiles/local/local_validation_profile.local.toml}"
export OPENFDD_VALIDATION_PROFILE="$VALIDATION_PROFILE"
export OPENFDD_SMOKE_PROFILE_PATH="$VALIDATION_PROFILE"
echo "    profile=$VALIDATION_PROFILE"
if [[ ! -f "$VALIDATION_PROFILE" ]]; then
  echo "ERROR: validation profile not found: $VALIDATION_PROFILE" >&2
  echo "Copy workspace/smoke-profiles/local/local_validation_profile.local.toml.example and configure." >&2
  exit 1
fi

if [[ "$QUICK_MIN" -gt 0 ]]; then
  echo "WARN: OPENFDD_VALIDATION_QUICK_MINUTES=$QUICK_MIN — not a full 1-hour acceptance run"
fi

"$ROOT/scripts/openfdd_validation_workspace_reset.sh" --dry-run | tee "$ORCH_DIR/reset_dry_run.txt"
"$ROOT/scripts/openfdd_validation_workspace_reset.sh" --confirm DELETE_VALIDATION_ARTIFACTS

if ! curl -fsS "$BASE/api/health" >/dev/null 2>&1; then
  echo "ERROR: stack not reachable at $BASE — start with ./scripts/openfdd_inspection_build.sh --build" >&2
  exit 1
fi

"$ROOT/scripts/openfdd_auth_smoke.sh" | tee "$ORCH_DIR/auth_smoke.log"
OPENFDD_UI_SMOKE_ARTIFACT="$ORCH_DIR/ui_smoke_pre" OPENFDD_UI_SMOKE_REPORTS=1 \
  "$ROOT/scripts/openfdd_ui_smoke.sh" | tee "$ORCH_DIR/ui_smoke_pre.log"

export OPENFDD_VALIDATION_ONE_HOUR=1
export OPENFDD_SMOKE_ARTIFACT_DIR="$ORCH_DIR/live_fdd_validation"
export OPENFDD_SMOKE_DURATION_HOURS="${OPENFDD_SMOKE_DURATION_HOURS:-1}"
export OPENFDD_SMOKE_INTERVAL_SECONDS="${OPENFDD_SMOKE_INTERVAL_SECONDS:-60}"
export OPENFDD_SMOKE_LIVE_FDD=1
export OPENFDD_SMOKE_CSV_APPEND=1
export OPENFDD_SMOKE_VALIDATE_MODBUS=1
export OPENFDD_SMOKE_VALIDATE_JSON_API="${OPENFDD_SMOKE_VALIDATE_JSON_API:-0}"
export OPENFDD_SMOKE_NO_DEMO_PASS=1

if [[ "$QUICK_MIN" -gt 0 ]]; then
  export BENCH_SMOKE_SHORT_FDD=1
  export BENCH_SMOKE_DURATION_MINUTES="$QUICK_MIN"
  export OPENFDD_SMOKE_INTERVAL_SECONDS=30
fi

if [[ -n "${OPENFDD_MODBUS_HOST:-}" ]]; then
  export OPENFDD_MODBUS_MODE=live
fi

set +e
"$ROOT/scripts/smoke_live_fdd_validation.sh" | tee "$ORCH_DIR/live_fdd_validation.log"
SMOKE_RC=${PIPESTATUS[0]}
set -e

VALIDATION_PASS=false
if [[ "$SMOKE_RC" -eq 0 ]]; then
  VALIDATION_PASS=true
fi

TOKEN="$(openfdd_auth_login_token "$BASE" "$AUTH" integrator)"
REPORT_BODY="$(jq -nc \
  --arg dir "$ORCH_DIR/live_fdd_validation" \
  --arg run "$RUN_TS" \
  --argjson pass "$VALIDATION_PASS" \
  '{artifact_dir:$dir,validation_run_id:$run,pass:$pass}')"

curl -fsS -X POST "$BASE/api/reports/from-validation-run" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d "$REPORT_BODY" \
  | tee "$ORCH_DIR/report_from_validation.json"

REPORT_ID="$(jq -r '.report_id // empty' "$ORCH_DIR/report_from_validation.json")"
if [[ -n "$REPORT_ID" ]]; then
  curl -fsS "$BASE/api/reports/${REPORT_ID}/download.pdf" \
    -H "Authorization: Bearer $TOKEN" \
    -o "$ORCH_DIR/validation_report.pdf" || true
  echo "Report PDF: $ORCH_DIR/validation_report.pdf"
  echo "Download URL: $BASE/api/reports/${REPORT_ID}/download.pdf"
fi

OPENFDD_UI_SMOKE_ARTIFACT="$ORCH_DIR/ui_smoke_post" OPENFDD_UI_SMOKE_REPORTS=1 \
  "$ROOT/scripts/openfdd_ui_smoke.sh" | tee "$ORCH_DIR/ui_smoke_post.log"

jq -nc \
  --arg ts "$RUN_TS" \
  --arg dir "$ORCH_DIR" \
  --argjson pass "$VALIDATION_PASS" \
  --arg report "$REPORT_ID" \
  '{validation_run_id:$ts,artifact_dir:$dir,pass:$pass,report_id:$report,finished_at:(now|todate)}' \
  >"$ORCH_DIR/final_summary.json"

if [[ "$VALIDATION_PASS" != true ]]; then
  echo "FAILED: validation did not pass — see $ORCH_DIR" >&2
  exit 1
fi

if [[ "$QUICK_MIN" -gt 0 ]]; then
  echo "Quick validation wiring PASS — run without OPENFDD_VALIDATION_QUICK_MINUTES for full 1-hour acceptance."
fi

echo "PASS — one-hour validation workflow complete: $ORCH_DIR"
exit 0
