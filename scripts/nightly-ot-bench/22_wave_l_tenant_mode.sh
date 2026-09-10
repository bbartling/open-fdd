#!/usr/bin/env bash
# Gate 22 - Wave L tenant mode / control plane smoke (mode OFF until Tier-2).
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib.sh"
load_bench_env
cd "$ROOT"

ART="${ARTIFACT_DIR:-$(artifact_dir)}"
mkdir -p "$ART"
LOG="$ART/wave_l_tenant_mode.log"
: >"$LOG"

central_auth_setup

health="$(curl -sS --max-time 30 "${CENTRAL_AUTH_HDR[@]+"${CENTRAL_AUTH_HDR[@]}"}" \
  "$CENTRAL_BASE/api/health")"
echo "$health" | tee "$ART/wave_l_health.json" >/dev/null
mt="$(echo "$health" | jq -r '.multi_tenant // false')"
ver="$(echo "$health" | jq -r '.version // empty')"
echo "health multi_tenant=$mt version=$ver" | tee -a "$LOG"

if [[ "$mt" == "true" ]]; then
  echo "FAIL: multi_tenant must be false until operator enables after Tier-2" | tee -a "$LOG"
  exit 1
fi

tenants="$(curl -sS --max-time 30 "${CENTRAL_AUTH_HDR[@]+"${CENTRAL_AUTH_HDR[@]}"}" \
  "$CENTRAL_BASE/api/tenants")"
echo "$tenants" | tee "$ART/wave_l_tenants.json" >/dev/null
ok="$(echo "$tenants" | jq -r '.ok // false')"
mt2="$(echo "$tenants" | jq -r '.multi_tenant // false')"
n="$(echo "$tenants" | jq -r '(.tenants // []) | length')"
legacy="$(echo "$tenants" | jq -r '[.tenants[]? | select(.id=="legacy")] | length')"
echo "tenants ok=$ok multi_tenant=$mt2 n=$n legacy=$legacy" | tee -a "$LOG"

if [[ "$ok" != "true" || "$mt2" == "true" || "$n" -lt 1 || "$legacy" -lt 1 ]]; then
  echo "FAIL: expected legacy control-plane listing with multi_tenant=false" | tee -a "$LOG"
  exit 1
fi

ok "Wave L tenant mode OFF + legacy control plane PASS"
exit 0
