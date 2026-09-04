#!/usr/bin/env bash
# Patch-cycle stress LAST: Railway hub + CSV matrix + light ZAP.
# Field OT is bensbench x86 → Railway MQTTS (no Raspberry Pi).
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib.sh"
load_bench_env
cd "$ROOT"

RAILWAY_BASE="${OPENFDD_API_BASE:-${RAILWAY_BASE:-https://openfdd-web-production-af99.up.railway.app}}"
export OPENFDD_API_BASE="$RAILWAY_BASE"
export CENTRAL_BASE="$RAILWAY_BASE"
export BASE="$RAILWAY_BASE"
export RAILWAY_ONLY=1
export RUN_CREEKSIDE_FULL="${RUN_CREEKSIDE_FULL:-1}"

if [[ -z "${RAILWAY_ADMIN_PASSWORD:-}" ]] && command -v railway >/dev/null 2>&1; then
  RAILWAY_ADMIN_PASSWORD="$(railway variable list --service openfdd-central-cQ-F --json 2>/dev/null \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("OPENFDD_ADMIN_PASSWORD",""))' || true)"
fi
if [[ -n "${RAILWAY_ADMIN_PASSWORD:-}" ]]; then
  export OPENFDD_ADMIN_PASSWORD="$RAILWAY_ADMIN_PASSWORD"
  export RAILWAY_ADMIN_PASSWORD
fi

ART="$(artifact_dir)"
export ARTIFACT_DIR="$ART"
REPORT="$ART/SUMMARY.md"
{
  echo "# Railway hub stress — $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo
  echo "- Hub: \`$RAILWAY_BASE\`"
  echo "- Field: bensbench x86 → Railway MQTTS (no Pi)"
  echo
} >"$REPORT"

OVERALL=0
run_named() {
  local title="$1"; shift
  # Re-assert Railway admin after any child that sourced local .env.
  if [[ -n "${RAILWAY_ADMIN_PASSWORD:-}" ]]; then
    export OPENFDD_ADMIN_PASSWORD="$RAILWAY_ADMIN_PASSWORD"
  fi
  hdr "$title"
  local log="$ART/$(echo "$title" | tr ' /' '__').log"
  set +e
  "$@" 2>&1 | tee "$log"
  local rc=${PIPESTATUS[0]}
  set -e
  if [[ "$rc" -eq 0 ]]; then
    echo "- **$title:** PASS" >>"$REPORT"
  else
    echo "- **$title:** FAIL (see log)" >>"$REPORT"
    OVERALL=1
  fi
  return 0
}

run_named "00 hub health + edges" bash -c '
  curl -sf --max-time 20 "$OPENFDD_API_BASE/api/health" | jq -e ".ok==true"
  fb="$(curl -sf --max-time 8 http://127.0.0.1:8081/health || true)"
  echo "fieldbus=$fb"
  TOK="$(curl -sf --max-time 20 -X POST "$OPENFDD_API_BASE/api/auth/login" \
    -H "Content-Type: application/json" \
    -d "$(jq -nc --arg p "$OPENFDD_ADMIN_PASSWORD" "{username:\"admin\",password:\$p}")" \
    | jq -r ".token // empty")"
  [[ -n "$TOK" ]]
  curl -sf --max-time 20 -H "Authorization: Bearer $TOK" "$OPENFDD_API_BASE/api/edges" \
    | jq -e "any(.edges[]?; .has_telemetry==true)"
'

run_named "01 synth59 Railway" \
  python3 "$ROOT/scripts/synthetic_59_target_pair_soak.py" --side ofdd --api-base "$RAILWAY_BASE"

run_named "02 gate 17" \
  env RUN_SYNTH59_HEALTH_MATRIX=1 "$DIR/17_synthetic_health_matrix_fault_hours.sh"

run_named "03 B100 Railway-only" \
  "$ROOT/scripts/gates/railway_b100_parity_spot.sh"

run_named "04 Creekside" \
  "$ROOT/scripts/gates/creekside_package_import_spot.sh"

run_named "05 gate 19" \
  "$DIR/19_engineering_bundle_validate.sh"

if [[ "${SKIP_ZAP:-0}" != "1" ]]; then
  ZART="$ROOT/reports/zap-railway_$(date -u +%Y%m%dT%H%M%SZ)"
  mkdir -p "$ZART"
  run_named "06 ZAP baseline" \
    docker run --rm -v "$ZART:/zap/wrk:rw" -t ghcr.io/zaproxy/zaproxy:stable \
      zap-baseline.py -t "$RAILWAY_BASE" -r zap_baseline.html -J zap_baseline.json -I
  echo "- ZAP artifacts: \`$ZART\`" >>"$REPORT"
fi

{
  echo
  echo "## Verdict"
  if [[ "$OVERALL" -eq 0 ]]; then
    echo "**PASS** — Railway hub CSV + field telemetry + ZAP."
  else
    echo "**FAIL** — see phase logs."
  fi
} >>"$REPORT"
echo "Report: $REPORT"
cat "$REPORT"
exit "$OVERALL"
