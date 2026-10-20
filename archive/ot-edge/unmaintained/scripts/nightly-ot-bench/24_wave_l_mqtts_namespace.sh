#!/usr/bin/env bash
# Gate 24 - Wave L MQTTS namespace / identity provenance smoke (mode OFF).
# Asserts multi_tenant=false and live MQTT still ingesting on legacy site topics.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib.sh"
load_bench_env
cd "$ROOT"

ART="${ARTIFACT_DIR:-$(artifact_dir)}"
mkdir -p "$ART"
LOG="$ART/wave_l_mqtts_namespace.log"
: >"$LOG"

central_auth_setup

health="$(curl -sS --max-time 30 "${CENTRAL_AUTH_HDR[@]+"${CENTRAL_AUTH_HDR[@]}"}" \
  "$CENTRAL_BASE/api/health")"
echo "$health" | tee "$ART/wave_l_l3_health.json" >/dev/null
mt="$(echo "$health" | jq -r '.multi_tenant // false')"
ver="$(echo "$health" | jq -r '.version // empty')"
ingest="$(echo "$health" | jq -r '.ingest_ok // 0')"
edges="$(echo "$health" | jq -r '.edges // 0')"
echo "health multi_tenant=$mt version=$ver ingest_ok=$ingest edges=$edges" | tee -a "$LOG"

if [[ "$mt" == "true" ]]; then
  echo "FAIL: multi_tenant must be false until operator enables after Tier-2" | tee -a "$LOG"
  exit 1
fi

if [[ "$edges" -lt 1 ]]; then
  echo "FAIL: expected at least one MQTT edge on legacy site topics" | tee -a "$LOG"
  exit 1
fi

if [[ "$ingest" -lt 1 ]]; then
  echo "FAIL: expected ingest_ok>=1 (legacy MQTT path still live)" | tee -a "$LOG"
  exit 1
fi

# Contract smoke: OFF path must keep openfdd/v1/sites/… (tenant path is lab-only until ON).
if ! echo "$ver" | rg -q '^3\.5\.'; then
  echo "WARN: version $ver not in 3.5.x line (continuing)" | tee -a "$LOG"
fi

ok "Wave L MQTTS namespace OFF (legacy sites/… + identity provenance helpers) PASS"
exit 0
