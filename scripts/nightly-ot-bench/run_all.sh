#!/usr/bin/env bash
# Full nightly OT gate: GHCR pull → health → BACnet 5007 → MQTT/Feather persistence.
# Writes a short markdown summary under reports/ (gitignored).
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib.sh"
load_bench_env
cd "$ROOT"

SKIP_PULL="${SKIP_PULL:-0}"
ART="$(artifact_dir)"
export ARTIFACT_DIR="$ART"
REPORT="$ART/SUMMARY.md"
STAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

{
  echo "# Nightly OT bench run — $STAMP"
  echo
  echo "- Root: \`$ROOT\`"
  echo "- Site/edge: \`${OPENFDD_SITE_ID}/${OPENFDD_EDGE_ID}\`"
  echo "- Fieldbus: \`$FIELDBUS_BASE\`  Central: \`$CENTRAL_BASE\`"
  echo "- Bench device: \`${BENCH_DEVICE}\`  Hosted: \`${HOSTED_DEVICE}\`"
  echo "- Recipe: react-ot (compose.react + fieldbus); pin \`\${OPENFDD_IMAGE_TAG:-sha-*}\`"
  echo "- Writes: \`BENCH_ALLOW_WRITES=${BENCH_ALLOW_WRITES:-0}\` (default read/poll only)"
  echo
} >"$REPORT"

run_phase() {
  local script="$1" title="$2"
  hdr "$title"
  local logfile="$ART/${script%.sh}.log"
  local rc=0
  set +e
  bash "$DIR/$script" 2>&1 | tee "$logfile"
  rc=${PIPESTATUS[0]}
  set -e
  if [[ "$rc" -eq 0 ]]; then
    echo "- **$title:** PASS" >>"$REPORT"
  else
    echo "- **$title:** FAIL (see \`${script%.sh}.log\`)" >>"$REPORT"
  fi
  return "$rc"
}

OVERALL=0
if [[ "$SKIP_PULL" != "1" ]]; then
  run_phase 00_pull_ghcr_up.sh "00 pull GHCR + up" || OVERALL=1
else
  echo "- **00 pull:** SKIPPED (SKIP_PULL=1)" >>"$REPORT"
  skip "pull/up skipped (SKIP_PULL=1)"
fi

run_phase 01_health_gates.sh "01 health gates" || OVERALL=1
run_phase 02_bacnet_ot.sh "02 BACnet OT (5007 + BIP + poll)" || OVERALL=1
run_phase 03_mqtt_feather_persist.sh "03 MQTTS + Feather persistence" || OVERALL=1
run_phase 04_modbus_ot.sh "04 Modbus OT (bench sim)" || OVERALL=1
run_phase 05_haystack.sh "05 Haystack API surface" || OVERALL=1
run_phase 06_csv_fdd_sql.sh "06 CSV import + SQL FDD (FC1)" || OVERALL=1

# 07 cloud-sim is opt-in: RUN_CLOUD_SIM=1 ./run_all.sh (needs bosspi reachable)
if [[ "${RUN_CLOUD_SIM:-0}" == "1" ]]; then
  run_phase 07_cloud_sim.sh "07 cloud-sim (remote Pi edge, instance 600000)" || OVERALL=1
else
  echo "- **07 cloud-sim:** SKIPPED (set RUN_CLOUD_SIM=1)" >>"$REPORT"
  skip "cloud-sim skipped (RUN_CLOUD_SIM=1 to enable)"
fi

# 08 weather trend soak (~30 min wall clock by default; WEATHER_SOAK_SECS to shorten).
# Runs bench-only if the Pi edge is down; full 599999+600000 trend when 07 ran.
run_phase 08_weather_trend.sh "08 weather trend + WB soak (599999/600000)" || OVERALL=1

# 09 REST/JSON edge driver (#540) — throwaway fieldbus + JSON sim; does not touch WB stack.
run_phase 09_rest_ot.sh "09 REST/JSON edge driver (#540)" || OVERALL=1

# React SPA / dashboard / honesty / MCP accuracy (GHCR tip + local web build).
run_phase 10_react_spa.sh "10 React SPA product surface" || OVERALL=1
run_phase 11_dashboard_apis_549.sh "11 dashboard APIs (#549)" || OVERALL=1
run_phase 12_parity_honesty_550.sh "12 parity honesty (#550 KEEP OPEN)" || OVERALL=1
run_phase 13_mcp_accuracy.sh "13 MCP accuracy vs central" || OVERALL=1

{
  echo
  echo "## Verdict"
  if [[ "$OVERALL" -eq 0 ]]; then
    echo "**PASS** — tip GHCR + React SPA + fieldbus OT through gates 00–13."
  else
    echo "**FAIL** — see phase logs in this directory."
  fi
  echo
  echo "## Recreate"
  echo '```bash'
  echo "cd $ROOT"
  echo "./scripts/nightly-ot-bench/run_all.sh"
  echo "# optional: RUN_CLOUD_SIM=1 BENCH_ALLOW_WRITES=1 SKIP_PULL=1"
  echo '```'
} >>"$REPORT"

echo
echo "${BOLD}Report: $REPORT${RST}"
cat "$REPORT"
exit "$OVERALL"
