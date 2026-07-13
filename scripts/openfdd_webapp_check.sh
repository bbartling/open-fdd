#!/usr/bin/env bash
# Full local web-app check — login + API + frontend (+ optional vitest).
#
#   ./scripts/openfdd_webapp_check.sh
#   ./scripts/openfdd_webapp_check.sh --base-url http://127.0.0.1:8080
#   ./scripts/openfdd_webapp_check.sh --skip-vitest
#
# Requires a running edge (./scripts/openfdd_cargo_up.sh or openfdd_local_up.sh)
# and workspace/auth.env.local (./scripts/openfdd_auth_init.sh --show-secrets).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE="${OPENFDD_API_BASE:-${OPENFDD_BRIDGE_BASE:-http://127.0.0.1:8080}}"
SKIP_VITEST=0
FAIL=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base-url) BASE="${2:?}"; shift 2 ;;
    --skip-vitest) SKIP_VITEST=1; shift ;;
    -h|--help)
      sed -n '2,12p' "$0"
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

export OPENFDD_API_BASE="$BASE"
export OPENFDD_BRIDGE_BASE="$BASE"
if [[ "$SKIP_VITEST" == "1" ]]; then
  export OPENFDD_SKIP_VITEST=1
fi

echo "========================================"
echo " Open-FDD webapp check"
echo " Base: $BASE"
echo "========================================"
echo

if ! curl -fsS --max-time 3 "$BASE/api/health" >/dev/null 2>&1; then
  echo "ERROR: nothing healthy at $BASE/api/health" >&2
  echo "Start the app first:" >&2
  echo "  ./scripts/openfdd_auth_init.sh --show-secrets" >&2
  echo "  ./scripts/openfdd_cargo_up.sh    # or ./scripts/openfdd_local_up.sh" >&2
  exit 1
fi

run() {
  local title="$1"
  shift
  echo "-------- $title --------"
  if "$@"; then
    echo
    return 0
  fi
  echo
  FAIL=1
  return 0
}

run "1/3 Login (all roles + SPA root)" \
  "$ROOT/scripts/openfdd_login_ui_smoke.sh"

run "2/3 Backend API" \
  "$ROOT/scripts/openfdd_api_check.sh" --base-url "$BASE"

run "3/3 Frontend SPA${SKIP_VITEST:+ (vitest skipped)}" \
  "$ROOT/scripts/openfdd_frontend_check.sh" --base-url "$BASE"

echo "========================================"
if [[ "$FAIL" -ne 0 ]]; then
  echo " WEBAPP CHECK FAILED"
  echo " See workspace/logs/*_check_*/ for response bodies"
  echo "========================================"
  exit 1
fi
echo " WEBAPP CHECK PASS"
echo "========================================"
