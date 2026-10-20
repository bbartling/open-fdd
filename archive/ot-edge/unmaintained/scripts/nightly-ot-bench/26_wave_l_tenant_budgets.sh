#!/usr/bin/env bash
# Gate 26 - Wave L tenant budgets smoke (mode OFF / budgets disabled).
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib.sh"
load_bench_env
cd "$ROOT"

ART="${ARTIFACT_DIR:-$(artifact_dir)}"
mkdir -p "$ART"
LOG="$ART/wave_l_tenant_budgets.log"
: >"$LOG"

central_auth_setup

health="$(curl -sS --max-time 30 "${CENTRAL_AUTH_HDR[@]+"${CENTRAL_AUTH_HDR[@]}"}" \
  "$CENTRAL_BASE/api/health")"
echo "$health" | tee "$ART/wave_l_l5_health.json" >/dev/null
mt="$(echo "$health" | jq -r '.multi_tenant // false')"
ver="$(echo "$health" | jq -r '.version // empty')"
echo "health multi_tenant=$mt version=$ver" | tee -a "$LOG"

if [[ "$mt" == "true" ]]; then
  echo "FAIL: multi_tenant must be false until operator enables after Tier-2" | tee -a "$LOG"
  exit 1
fi

budgets="$(curl -sS --max-time 30 "${CENTRAL_AUTH_HDR[@]+"${CENTRAL_AUTH_HDR[@]}"}" \
  "$CENTRAL_BASE/api/tenants/budgets")"
echo "$budgets" | tee "$ART/wave_l_l5_budgets.json" >/dev/null
ok="$(echo "$budgets" | jq -r '.ok')"
enabled="$(echo "$budgets" | jq -r '.budgets.enabled')"
mt2="$(echo "$budgets" | jq -r '.multi_tenant')"
echo "budgets ok=$ok enabled=$enabled multi_tenant=$mt2" | tee -a "$LOG"

if [[ "$ok" != "true" || "$enabled" != "false" || "$mt2" == "true" ]]; then
  echo "FAIL: expected budgets.enabled=false while multi_tenant=false" | tee -a "$LOG"
  exit 1
fi

caps="$(curl -sS --max-time 30 "${CENTRAL_AUTH_HDR[@]+"${CENTRAL_AUTH_HDR[@]}"}" \
  "$CENTRAL_BASE/api/capabilities")"
echo "$caps" | tee "$ART/wave_l_l5_capabilities.json" >/dev/null
tb="$(echo "$caps" | jq -r '.capabilities.tenant_budgets')"
echo "capabilities.tenant_budgets=$tb" | tee -a "$LOG"
if [[ "$tb" != "false" ]]; then
  echo "FAIL: expected capabilities.tenant_budgets=false while mode OFF" | tee -a "$LOG"
  exit 1
fi

ok "Wave L tenant budgets OFF (disabled while multi_tenant=false) PASS"
exit 0
