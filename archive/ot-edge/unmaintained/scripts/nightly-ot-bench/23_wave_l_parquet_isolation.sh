#!/usr/bin/env bash
# Gate 23 — Wave L Parquet tenant-root isolation smoke (mode OFF until Tier-2).
# Asserts historian_prefix is empty when multi_tenant=false (single-hub layout).
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib.sh"
load_bench_env
cd "$ROOT"

ART="${ARTIFACT_DIR:-$(artifact_dir)}"
mkdir -p "$ART"
LOG="$ART/wave_l_parquet_isolation.log"
: >"$LOG"

central_auth_setup

health="$(curl -sS --max-time 30 "${CENTRAL_AUTH_HDR[@]+"${CENTRAL_AUTH_HDR[@]}"}" \
  "$CENTRAL_BASE/api/health")"
echo "$health" | tee "$ART/wave_l_l2_health.json" >/dev/null
mt="$(echo "$health" | jq -r '.multi_tenant // false')"
ver="$(echo "$health" | jq -r '.version // empty')"
echo "health multi_tenant=$mt version=$ver" | tee -a "$LOG"

if [[ "$mt" == "true" ]]; then
  echo "FAIL: multi_tenant must be false until operator enables after Tier-2" | tee -a "$LOG"
  exit 1
fi

tenants="$(curl -sS --max-time 30 "${CENTRAL_AUTH_HDR[@]+"${CENTRAL_AUTH_HDR[@]}"}" \
  "$CENTRAL_BASE/api/tenants")"
echo "$tenants" | tee "$ART/wave_l_l2_tenants.json" >/dev/null
ok="$(echo "$tenants" | jq -r '.ok // false')"
prefix="$(echo "$tenants" | jq -r '.historian_prefix // empty')"
legacy="$(echo "$tenants" | jq -r '[.tenants[]? | select(.id=="legacy")] | length')"
echo "tenants ok=$ok historian_prefix='$prefix' legacy=$legacy" | tee -a "$LOG"

if [[ "$ok" != "true" || "$legacy" -lt 1 ]]; then
  echo "FAIL: expected legacy control-plane listing" | tee -a "$LOG"
  exit 1
fi

# Mode OFF must keep today's hub root (empty prefix = no tenants/… partition).
if [[ -n "$prefix" ]]; then
  echo "FAIL: historian_prefix must be empty when multi_tenant=false (got '$prefix')" | tee -a "$LOG"
  exit 1
fi

ok "Wave L Parquet isolation OFF (hub root, empty historian_prefix) PASS"
exit 0
