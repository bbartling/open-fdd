#!/usr/bin/env bash
# Patch-cycle stress LAST: Railway hub + CSV matrix + light ZAP + auth/MCP.
# Field OT is bensbench x86 → Railway MQTTS (no Raspberry Pi).
#
# Truthful qualification: SUMMARY.md is generated from qualification_manifest.json
# via scripts/qualification/write_manifest.py — never a static PASS sentence.
# Required SKIPPED/BLOCKED/ERROR ⇒ not fully_qualified.
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
if [[ "$RAILWAY_BASE" != https://* ]]; then
  echo "ERROR: Railway field stress requires https:// hub, got: $RAILWAY_BASE" >&2
  exit 1
fi
EXPECTED_EDGE_ID="${EXPECTED_EDGE_ID:-}"
EXPECTED_SITE_ID="${EXPECTED_SITE_ID:-}"
ACCEPT_ZAP_MEDIUM="${ACCEPT_ZAP_MEDIUM:-1}"
QUAL="$ROOT/scripts/qualification"
MANIFEST_PY="$QUAL/write_manifest.py"

if [[ -z "${RAILWAY_ADMIN_PASSWORD:-}" ]] && command -v railway >/dev/null 2>&1; then
  RAILWAY_ADMIN_PASSWORD="$(railway variable list --service openfdd-central-cQ-F --json 2>/dev/null \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("OPENFDD_ADMIN_PASSWORD",""))' || true)"
fi
if [[ -n "${RAILWAY_ADMIN_PASSWORD:-}" ]]; then
  export OPENFDD_ADMIN_PASSWORD="$RAILWAY_ADMIN_PASSWORD"
  export RAILWAY_ADMIN_PASSWORD
fi
if [[ -z "${OPENFDD_AGENT_PASSWORD:-}" ]] && command -v railway >/dev/null 2>&1; then
  OPENFDD_AGENT_PASSWORD="$(railway variable list --service openfdd-central-cQ-F --json 2>/dev/null \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("OPENFDD_AGENT_PASSWORD",""))' || true)"
  export OPENFDD_AGENT_PASSWORD
fi

ART="$(artifact_dir)"
export ARTIFACT_DIR="$ART"
MANIFEST="$ART/qualification_manifest.json"
RUN_ID="$(basename "$ART")"
CANDIDATE_SHA="$(curl -sf --max-time 20 "$RAILWAY_BASE/api/health" 2>/dev/null \
  | jq -r '.version // .git_sha // empty' || true)"
HARNESS_SHA="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || true)"

python3 "$MANIFEST_PY" create \
  --out "$MANIFEST" \
  --run-id "$RUN_ID" \
  --environment-class railway_field \
  --hub-base "$RAILWAY_BASE" \
  --candidate-sha "${CANDIDATE_SHA:-}" \
  --harness-sha "${HARNESS_SHA:-}" \
  --required 00_hub_health_edges \
  --required 01_synth59 \
  --required 02_gate17 \
  --required 03_b100 \
  --required 04_creekside \
  --required 05_gate19 \
  --required 06_zap_baseline \
  --required 07_auth_role_matrix \
  --required 08_mcp_accuracy

record_gate() {
  local gate="$1" status="$2" title="$3" reason="${4:-}"
  shift 4 || true
  local args=(python3 "$MANIFEST_PY" record --manifest "$MANIFEST" --gate "$gate" --status "$status" --title "$title")
  [[ -n "$reason" ]] && args+=(--reason "$reason")
  local art
  for art in "$@"; do
    [[ -n "$art" ]] && args+=(--artifact "$art")
  done
  "${args[@]}"
}

run_gate() {
  local gate="$1" title="$2"
  shift 2
  if [[ -n "${RAILWAY_ADMIN_PASSWORD:-}" ]]; then
    export OPENFDD_ADMIN_PASSWORD="$RAILWAY_ADMIN_PASSWORD"
  fi
  hdr "$title"
  local log="$ART/${gate}.log"
  local t0=$SECONDS
  set +e
  "$@" 2>&1 | tee "$log"
  local rc=${PIPESTATUS[0]}
  set -e
  local dur=$((SECONDS - t0))
  if [[ "$rc" -eq 0 ]]; then
    python3 "$MANIFEST_PY" record --manifest "$MANIFEST" --gate "$gate" --status PASS \
      --title "$title" --artifact "$log" --duration-secs "$dur"
  else
    python3 "$MANIFEST_PY" record --manifest "$MANIFEST" --gate "$gate" --status FAIL \
      --title "$title" --reason "exit=$rc" --artifact "$log" --duration-secs "$dur"
  fi
  return 0
}

# --- 00 hub health + expected edge (strict; no masked probe failures) ---
run_gate "00_hub_health_edges" "00 hub health + edges" bash -euo pipefail -c '
  set -euo pipefail
  HEALTH="$(curl -sf --max-time 20 "$OPENFDD_API_BASE/api/health")"
  echo "$HEALTH" | tee "'"$ART"'/health.json" | jq -e ".ok==true" >/dev/null
  fb="$(curl -sf --max-time 8 http://127.0.0.1:8081/health || true)"
  echo "fieldbus=$fb" | tee "'"$ART"'/fieldbus_health.txt"
  TOK="$(curl -sf --max-time 20 -X POST "$OPENFDD_API_BASE/api/auth/login" \
    -H "Content-Type: application/json" \
    -d "$(jq -nc --arg p "$OPENFDD_ADMIN_PASSWORD" "{username:\"admin\",password:\$p}")" \
    | jq -r ".token // empty")"
  test -n "$TOK"
  EDGES="$(curl -sf --max-time 20 -H "Authorization: Bearer $TOK" "$OPENFDD_API_BASE/api/edges")"
  echo "$EDGES" | tee "'"$ART"'/edges.json" >/dev/null
  if [[ -n "'"$EXPECTED_EDGE_ID"'" ]]; then
    echo "$EDGES" | jq -e --arg e "'"$EXPECTED_EDGE_ID"'" \
      "any(.edges[]?; .edge_id==\$e and .has_telemetry==true)" >/dev/null
  elif [[ -n "'"$EXPECTED_SITE_ID"'" ]]; then
    echo "$EDGES" | jq -e --arg s "'"$EXPECTED_SITE_ID"'" \
      "any(.edges[]?; ((.site_id//.building_id//\"\")==\$s) and .has_telemetry==true)" >/dev/null
  else
    echo "$EDGES" | jq -e "any(.edges[]?; .has_telemetry==true)" >/dev/null
  fi
'

run_gate "01_synth59" "01 synth59 Railway" \
  python3 "$ROOT/scripts/synthetic_59_target_pair_soak.py" --side ofdd --api-base "$RAILWAY_BASE"

run_gate "02_gate17" "02 gate 17" \
  env RUN_SYNTH59_HEALTH_MATRIX=1 "$DIR/17_synthetic_health_matrix_fault_hours.sh"

run_gate "03_b100" "03 B100 Railway-only" \
  "$ROOT/scripts/gates/railway_b100_parity_spot.sh"

run_gate "04_creekside" "04 Creekside" \
  "$ROOT/scripts/gates/creekside_package_import_spot.sh"

run_gate "05_gate19" "05 gate 19" \
  "$DIR/19_engineering_bundle_validate.sh"

# --- 06 ZAP baseline (public); SKIP_ZAP ⇒ SKIPPED required ⇒ not fully_qualified ---
if [[ "${SKIP_ZAP:-0}" == "1" ]]; then
  record_gate "06_zap_baseline" SKIPPED "06 ZAP baseline" \
    "SKIP_ZAP=1 — required security gate omitted; run not fully_qualified"
else
  ZART="$ROOT/reports/zap-railway_$(date -u +%Y%m%dT%H%M%SZ)"
  mkdir -p "$ZART"
  hdr "06 ZAP baseline"
  set +e
  docker run --rm -v "$ZART:/zap/wrk:rw" -t ghcr.io/zaproxy/zaproxy:stable \
    zap-baseline.py -t "$RAILWAY_BASE" -r zap_baseline.html -J zap_baseline.json -I \
    2>&1 | tee "$ART/06_zap_baseline.log"
  zap_rc=${PIPESTATUS[0]}
  set -e
  ZJSON="$ZART/zap_baseline.json"
  if [[ ! -s "$ZJSON" ]]; then
    record_gate "06_zap_baseline" ERROR "06 ZAP baseline" \
      "missing/empty zap_baseline.json (scanner startup or truncate); docker_rc=$zap_rc" \
      "$ART/06_zap_baseline.log"
  else
    ZARGS=(python3 "$QUAL/zap_baseline_verdict.py" --report "$ZJSON" --out "$ART/zap_measured.json")
    [[ "$ACCEPT_ZAP_MEDIUM" == "1" ]] && ZARGS+=(--accept-medium)
    set +e
    "${ZARGS[@]}" 2>&1 | tee -a "$ART/06_zap_baseline.log"
    zverdict=${PIPESTATUS[0]}
    set -e
    if [[ "$zverdict" -eq 0 ]]; then
      record_gate "06_zap_baseline" PASS "06 ZAP baseline" \
        "public baseline; High=0; Medium disposition ACCEPT_ZAP_MEDIUM=$ACCEPT_ZAP_MEDIUM (not authenticated AF scan)" \
        "$ZJSON" "$ART/zap_measured.json" "$ART/06_zap_baseline.log"
    elif grep -qE '^ERROR: (malformed|missing|ZAP JSON)' "$ART/06_zap_baseline.log" 2>/dev/null; then
      record_gate "06_zap_baseline" ERROR "06 ZAP baseline" \
        "malformed/invalid zap_baseline.json (scanner evidence unusable); exit=$zverdict" \
        "$ZJSON" "$ART/06_zap_baseline.log"
    else
      record_gate "06_zap_baseline" FAIL "06 ZAP baseline" \
        "zap_baseline_verdict exit=$zverdict (High or unaccepted Medium)" \
        "$ZJSON" "$ART/06_zap_baseline.log"
    fi
  fi
  echo "$ZART" >"$ART/zap_artifact_dir.txt"
fi

# --- 07 auth role matrix ---
run_gate "07_auth_role_matrix" "07 auth role matrix" \
  env ARTIFACT_DIR="$ART/auth_matrix" "$QUAL/auth_role_matrix.sh"

# --- 08 MCP accuracy (Railway-only; no local central fallback) ---
if [[ -z "${OPENFDD_MCP_IMAGE:-}" ]]; then
  # Derive from hub version tag when possible
  TAG="$(jq -r '.version // empty' "$ART/health.json" 2>/dev/null | sed -n 's/.*+\([a-f0-9]\{7,\}\).*/sha-\1/p' | head -c 11 || true)"
  if [[ -n "$TAG" && ${#TAG} -ge 11 ]]; then
    export OPENFDD_MCP_IMAGE="ghcr.io/bbartling/openfdd-mcp:${TAG}"
  fi
fi
if [[ -z "${OPENFDD_MCP_IMAGE:-}" ]]; then
  record_gate "08_mcp_accuracy" BLOCKED "08 MCP accuracy" \
    "OPENFDD_MCP_IMAGE unset and could not derive sha-* from health — set exact MCP image"
elif ! command -v docker >/dev/null; then
  record_gate "08_mcp_accuracy" BLOCKED "08 MCP accuracy" "docker not available on runner"
else
  run_gate "08_mcp_accuracy" "08 Railway MCP accuracy" \
    "$QUAL/railway_mcp_accuracy.sh"
fi

# Finalize — SUMMARY generated from recorded gates only
set +e
python3 "$MANIFEST_PY" finalize --manifest "$MANIFEST" --summary-md "$ART/SUMMARY.md"
FINAL_RC=$?
set -e
echo "Report: $ART/SUMMARY.md"
echo "Manifest: $MANIFEST"
cat "$ART/SUMMARY.md"
exit "$FINAL_RC"
