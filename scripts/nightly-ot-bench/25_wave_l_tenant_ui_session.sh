#!/usr/bin/env bash
# Gate 25 - Wave L tenant UI/session smoke (mode OFF / single domain).
# Asserts /api/auth/me + /api/tenants agree on legacy active tenant; select no-op.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib.sh"
load_bench_env
cd "$ROOT"

ART="${ARTIFACT_DIR:-$(artifact_dir)}"
mkdir -p "$ART"
LOG="$ART/wave_l_tenant_ui_session.log"
: >"$LOG"

central_auth_setup

health="$(curl -sS --max-time 30 "${CENTRAL_AUTH_HDR[@]+"${CENTRAL_AUTH_HDR[@]}"}" \
  "$CENTRAL_BASE/api/health")"
echo "$health" | tee "$ART/wave_l_l4_health.json" >/dev/null
mt="$(echo "$health" | jq -r '.multi_tenant // false')"
ver="$(echo "$health" | jq -r '.version // empty')"
echo "health multi_tenant=$mt version=$ver" | tee -a "$LOG"

if [[ "$mt" == "true" ]]; then
  echo "FAIL: multi_tenant must be false until operator enables after Tier-2" | tee -a "$LOG"
  exit 1
fi

tenants="$(curl -sS --max-time 30 "${CENTRAL_AUTH_HDR[@]+"${CENTRAL_AUTH_HDR[@]}"}" \
  "$CENTRAL_BASE/api/tenants")"
echo "$tenants" | tee "$ART/wave_l_l4_tenants.json" >/dev/null
active="$(echo "$tenants" | jq -r '.active_tenant_id // empty')"
mt2="$(echo "$tenants" | jq -r '.multi_tenant // false')"
echo "tenants active=$active multi_tenant=$mt2" | tee -a "$LOG"
if [[ "$active" != "legacy" || "$mt2" == "true" ]]; then
  echo "FAIL: expected active_tenant_id=legacy with multi_tenant=false" | tee -a "$LOG"
  exit 1
fi

me="$(curl -sS --max-time 30 "${CENTRAL_AUTH_HDR[@]+"${CENTRAL_AUTH_HDR[@]}"}" \
  "$CENTRAL_BASE/api/auth/me")"
echo "$me" | tee "$ART/wave_l_l4_auth_me.json" >/dev/null
me_ok="$(echo "$me" | jq -r '.ok // false')"
me_mt="$(echo "$me" | jq -r '.multi_tenant // false')"
me_tid="$(echo "$me" | jq -r '.active_tenant_id // empty')"
echo "auth/me ok=$me_ok multi_tenant=$me_mt active=$me_tid" | tee -a "$LOG"
if [[ "$me_ok" != "true" || "$me_mt" == "true" || "$me_tid" != "legacy" ]]; then
  echo "FAIL: auth/me must echo legacy session while mode OFF" | tee -a "$LOG"
  exit 1
fi

sel="$(curl -sS --max-time 30 "${CENTRAL_AUTH_HDR[@]+"${CENTRAL_AUTH_HDR[@]}"}" \
  -X POST "$CENTRAL_BASE/api/tenants/select" \
  -H "Content-Type: application/json" \
  -d '{"tenant_id":"legacy"}')"
echo "$sel" | tee "$ART/wave_l_l4_select.json" >/dev/null
sel_ok="$(echo "$sel" | jq -r '.ok // false')"
sel_tid="$(echo "$sel" | jq -r '.active_tenant_id // empty')"
sel_tok="$(echo "$sel" | jq -r '.token // .access_token // empty')"
echo "select ok=$sel_ok active=$sel_tid token=${sel_tok:+set}" | tee -a "$LOG"
if [[ "$sel_ok" != "true" || "$sel_tid" != "legacy" || -n "$sel_tok" ]]; then
  echo "FAIL: OFF select must no-op legacy without token rotation" | tee -a "$LOG"
  exit 1
fi

caps="$(curl -sS --max-time 30 "${CENTRAL_AUTH_HDR[@]+"${CENTRAL_AUTH_HDR[@]}"}" \
  "$CENTRAL_BASE/api/capabilities")"
echo "$caps" | tee "$ART/wave_l_l4_capabilities.json" >/dev/null
ts="$(echo "$caps" | jq -r '.capabilities.tenant_session // false')"
echo "capabilities.tenant_session=$ts" | tee -a "$LOG"
if [[ "$ts" != "true" ]]; then
  echo "FAIL: expected capabilities.tenant_session=true" | tee -a "$LOG"
  exit 1
fi

ok "Wave L tenant UI/session OFF (single domain / legacy) PASS"
exit 0
