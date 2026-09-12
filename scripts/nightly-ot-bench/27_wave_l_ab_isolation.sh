#!/usr/bin/env bash
# Gate 27 — Wave L L6 A?B isolation + tip digest readiness (mode OFF on field).
# Runs Tier-2 synthetic harness locally; asserts Railway multi_tenant=false.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib.sh"
load_bench_env
cd "$ROOT"

ART="${ARTIFACT_DIR:-$(artifact_dir)}"
mkdir -p "$ART"
LOG="$ART/wave_l_ab_isolation.log"
: >"$LOG"

central_auth_setup

health="$(curl -sS --max-time 30 "${CENTRAL_AUTH_HDR[@]+"${CENTRAL_AUTH_HDR[@]}"}" \
  "$CENTRAL_BASE/api/health")"
echo "$health" | tee "$ART/wave_l_l6_health.json" >/dev/null
mt="$(echo "$health" | jq -r '.multi_tenant // false')"
ver="$(echo "$health" | jq -r '.version // empty')"
echo "health multi_tenant=$mt version=$ver" | tee -a "$LOG"

if [[ "$mt" == "true" ]]; then
  echo "FAIL: multi_tenant must be false until operator enables after Tier-2" | tee -a "$LOG"
  exit 1
fi

# Tier-2 synthetic A?B (no live OT / no mode ON).
export ARTIFACT_DIR="$ART/ab_harness"
mkdir -p "$ARTIFACT_DIR"
bash "$ROOT/scripts/qualification/wave_l_ab_isolation_harness.sh" 2>&1 | tee -a "$LOG"
cp -f "$ARTIFACT_DIR/ab_isolation_matrix.json" "$ART/ab_isolation_matrix.json" 2>/dev/null || true

# Tip digest scan when docker available (field runners often have it).
TAG="$(echo "$ver" | sed -n 's/.*+\([a-f0-9]\{7,\}\).*/sha-\1/p' | head -c 11 || true)"
if [[ -n "$TAG" && ${#TAG} -ge 11 ]] && command -v docker >/dev/null 2>&1; then
  export OPENFDD_IMAGE_TAG="$TAG"
  export ARTIFACT_DIR="$ART/digest"
  mkdir -p "$ARTIFACT_DIR"
  # Hub-only is acceptable if fieldbus lag; full tip preferred.
  set +e
  bash "$ROOT/scripts/check_ghcr_tip_stack.sh" "$TAG" 2>&1 | tee -a "$LOG"
  tip_rc=${PIPESTATUS[0]}
  set -e
  if [[ "$tip_rc" -ne 0 ]]; then
    echo "FAIL: tip digest scan for $TAG" | tee -a "$LOG"
    exit 1
  fi
  echo "tip_digest=$TAG PASS" | tee -a "$LOG"
else
  echo "SKIP tip digest docker scan (tag='$TAG' docker=$(command -v docker || echo missing))" | tee -a "$LOG"
fi

ok "Wave L A?B isolation harness + mode OFF PASS"
exit 0
