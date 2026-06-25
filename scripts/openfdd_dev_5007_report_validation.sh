#!/usr/bin/env bash
# Dev-only 5007 RCx validation/report orchestration (profile-driven, no bench hardcoding in Rust).
#
#   OPENFDD_VALIDATION_PROFILE=workspace/smoke-profiles/local/local_5007_validation.local.toml \
#     ./scripts/openfdd_dev_5007_report_validation.sh
#
# Quick wiring test (not 1-hour acceptance):
#   OPENFDD_DEV_VALIDATION_DRY_RUN=1 ./scripts/openfdd_dev_5007_report_validation.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_auth_lib.sh
source "$ROOT/scripts/openfdd_auth_lib.sh"

BASE="${OPENFDD_API_BASE:-http://127.0.0.1:8080}"
AUTH="${OPENFDD_AUTH_ENV:-$ROOT/workspace/auth.env.local}"
PROFILE="${OPENFDD_VALIDATION_PROFILE:-$ROOT/workspace/smoke-profiles/local/local_5007_validation.local.toml}"
DRY="${OPENFDD_DEV_VALIDATION_DRY_RUN:-0}"
SKIP_BROWSER="${OPENFDD_DEV_VALIDATION_SKIP_BROWSER:-0}"

echo "==> Open-FDD dev RCx validation harness"
echo "    base=$BASE"
echo "    profile=$PROFILE"

if [[ ! -f "$PROFILE" ]]; then
  echo "ERROR: validation profile not found: $PROFILE" >&2
  echo "Copy workspace/smoke-profiles/local/local_5007_validation.local.toml.example and configure." >&2
  exit 1
fi

if ! curl -fsS "$BASE/api/health" >/dev/null 2>&1; then
  echo "ERROR: stack not reachable at $BASE — start with ./scripts/openfdd_inspection_build.sh --build" >&2
  exit 1
fi

token="$(openfdd_auth_login_token "$BASE" "$AUTH" integrator)" || {
  echo "ERROR: integrator login failed" >&2
  exit 1
}
echo "OK: auth login"

export OPENFDD_VALIDATION_PROFILE="$PROFILE"
export OPENFDD_SMOKE_PROFILE_PATH="$PROFILE"

PROFILE_ABS="$PROFILE"
if [[ "$PROFILE_ABS" != /* ]]; then
  PROFILE_ABS="$ROOT/$PROFILE_ABS"
fi

ARGS=(
  --base-url "$BASE"
  --profile "$PROFILE_ABS"
  --auth-env "$AUTH"
  --duration-minutes "${OPENFDD_DEV_VALIDATION_MINUTES:-60}"
  --bacnet-interval-seconds "${OPENFDD_DEV_VALIDATION_BACNET_INTERVAL:-60}"
  --driver-interval-seconds "${OPENFDD_DEV_VALIDATION_DRIVER_INTERVAL:-300}"
  --report
)
if [[ "$DRY" == "1" ]]; then
  ARGS+=(--dry-run --skip-browser)
fi
if [[ "$SKIP_BROWSER" == "1" ]]; then
  ARGS+=(--skip-browser)
fi
ARGS+=(--skip-haystack-if-not-configured --skip-modbus-if-not-configured)

set +e
cargo run --quiet --manifest-path "$ROOT/edge/Cargo.toml" --bin openfdd_dev_validation -- "${ARGS[@]}"
RC=$?
set -e

if [[ "$RC" -eq 0 ]]; then
  echo "RESULT: PASS"
else
  echo "RESULT: FAIL (exit $RC)"
fi

ARTIFACT="$(find "$ROOT/workspace/logs" -maxdepth 1 -type d -name 'dev_5007_validation_*' 2>/dev/null | sort | tail -1 || true)"
if [[ -n "$ARTIFACT" ]]; then
  echo "artifact_dir=$ARTIFACT"
  if [[ -f "$ARTIFACT/dev_validation_report.json" ]]; then
    echo "report_json=$ARTIFACT/dev_validation_report.json"
  fi
  if [[ -f "$ARTIFACT/status.txt" ]]; then
    echo "status=$(cat "$ARTIFACT/status.txt")"
  fi
fi

echo "Reports UI: ${BASE}/#/reports"
exit "$RC"
