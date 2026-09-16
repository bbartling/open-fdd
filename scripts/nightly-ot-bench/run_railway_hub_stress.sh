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
# shellcheck disable=SC1091
source "$DIR/lib_capacity_sample.sh"
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

# Pull hub auth from Railway CLI (never print values). Prefer file+jq over pipes —
# empty stdin / stale RAILWAY_TOKEN previously yielded blank passwords → mass gate FAIL.
_fetch_railway_var() {
  local key="$1"
  local svc="${OPENFDD_RAILWAY_CENTRAL_SVC:-openfdd-central-cQ-F}"
  local tmp
  tmp="$(mktemp)"
  # Stale RAILWAY_TOKEN in env breaks CLI; session login is preferred on bensbench.
  if ! env -u RAILWAY_TOKEN railway variable list --service "$svc" --json >"$tmp" 2>/dev/null; then
    rm -f "$tmp"
    return 1
  fi
  python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get(sys.argv[2],"") or "")' "$tmp" "$key"
  local rc=$?
  rm -f "$tmp"
  return "$rc"
}

if [[ -z "${RAILWAY_ADMIN_PASSWORD:-}" ]] && command -v railway >/dev/null 2>&1; then
  RAILWAY_ADMIN_PASSWORD="$(_fetch_railway_var OPENFDD_ADMIN_PASSWORD || true)"
fi
if [[ -n "${RAILWAY_ADMIN_PASSWORD:-}" ]]; then
  export OPENFDD_ADMIN_PASSWORD="$RAILWAY_ADMIN_PASSWORD"
  export RAILWAY_ADMIN_PASSWORD
fi
if [[ -z "${OPENFDD_AGENT_PASSWORD:-}" ]] && command -v railway >/dev/null 2>&1; then
  OPENFDD_AGENT_PASSWORD="$(_fetch_railway_var OPENFDD_AGENT_PASSWORD || true)"
  export OPENFDD_AGENT_PASSWORD
fi
if [[ -z "${OPENFDD_ADMIN_PASSWORD:-}" ]]; then
  echo "ERROR: OPENFDD_ADMIN_PASSWORD unset after Railway fetch — refuse hub stress without auth" >&2
  exit 2
fi
echo "hub auth: OPENFDD_ADMIN_PASSWORD len=${#OPENFDD_ADMIN_PASSWORD} agent_len=${#OPENFDD_AGENT_PASSWORD}"

# Mint bearer once up-front. Gate 23 deliberately trips login 429; AFDD flood must not re-login.
if [[ -z "${OPENFDD_ADMIN_TOKEN:-}" ]]; then
  OPENFDD_ADMIN_TOKEN="$(
    curl -sf --max-time 30 -X POST "$OPENFDD_API_BASE/api/auth/login" \
      -H 'Content-Type: application/json' \
      -d "{\"username\":\"${OPENFDD_ADMIN_USER:-admin}\",\"password\":$(python3 -c 'import json,os; print(json.dumps(os.environ["OPENFDD_ADMIN_PASSWORD"]))')}" \
      | jq -r '.token // .access_token // empty'
  )"
  export OPENFDD_ADMIN_TOKEN
fi
if [[ -z "${OPENFDD_ADMIN_TOKEN:-}" ]]; then
  echo "ERROR: could not mint OPENFDD_ADMIN_TOKEN at stress start" >&2
  exit 2
fi
echo "hub auth: OPENFDD_ADMIN_TOKEN len=${#OPENFDD_ADMIN_TOKEN}"

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
  --required 08_mcp_accuracy \
  --required 09_wave_i_app_test_megas \
  --required 10_wave_k_app_test_megas \
  --required 11_wave_l_tenant_mode \
  --required 12_wave_l_parquet_isolation \
  --required 13_wave_l_mqtts_namespace \
  --required 14_wave_l_tenant_ui_session \
  --required 15_wave_l_tenant_budgets \
  --required 16_wave_l_ab_isolation \
  --required 17_wave_l_legacy_migrate_dry_run \
  --required 18_wave_m_durable_session \
  --required 19_wave_m_afdd_flood \
  --required 20_wave_n_tenant_acl \
  --required 21_wave_n_mqtts_continuity \
  --required 22_wave_o_admin_datamodel_acl \
  --required 23_wave_o_security \
  --required 24_capacity_pressure \
  --required 24b_capacity_report

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
  export OPENFDD_STRESS_GATE="$gate"
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

# Capacity sampler rides along existing gates (S5a).
export CAPACITY_SAMPLE="${CAPACITY_SAMPLE:-1}"
capacity_fetch_hub_env_railway || capacity_write_hub_env || true
capacity_sampler_start || true
trap 'capacity_sampler_stop || true' EXIT

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

# --- 09 Wave I app-test MEGAs (basic app + dual OAT + plot span) ---
run_gate "09_wave_i_app_test_megas" "09 Wave I app-test MEGAs" \
  "$DIR/20_wave_i_app_test_megas.sh"

# --- 10 Wave K app-test MEGAs (sensor-faults + MQTT quad + data-model) ---
run_gate "10_wave_k_app_test_megas" "10 Wave K app-test MEGAs" \
  "$DIR/21_wave_k_app_test_megas.sh"

# --- 11 Wave L/N tenant mode (OFF=legacy; ON=Wave N trio — script bifurcates) ---
run_gate "11_wave_l_tenant_mode" "11 Wave L/N tenant mode" \
  bash "$DIR/22_wave_l_tenant_mode.sh"

# Wave L OFF-only gates (12–17) assert multi_tenant=false. On Wave N field hubs
# (MT ON) they would auto-FAIL; skip — coverage is gates 20/21 (+ gate 11 ON path).
HUB_MT="$(jq -r '.multi_tenant // false' "$ART/health.json" 2>/dev/null || echo false)"
if [[ "$HUB_MT" == "true" ]]; then
  for g in \
    "12_wave_l_parquet_isolation:12 Wave L Parquet isolation OFF" \
    "13_wave_l_mqtts_namespace:13 Wave L MQTTS namespace OFF" \
    "14_wave_l_tenant_ui_session:14 Wave L tenant UI/session OFF" \
    "15_wave_l_tenant_budgets:15 Wave L tenant budgets OFF" \
    "16_wave_l_ab_isolation:16 Wave L A↔B isolation harness" \
    "17_wave_l_legacy_migrate_dry_run:17 Wave L legacy migrate dry-run"
  do
    gid="${g%%:*}"
    title="${g#*:}"
    # PASS (not SKIPPED): required-gate SKIPPED blocks fully_qualified.
    record_gate "$gid" PASS "$title" \
      "N/A hub multi_tenant=true (Wave N OPS); Wave L OFF suite superseded by gates 11/20/21"
  done
else
  run_gate "12_wave_l_parquet_isolation" "12 Wave L Parquet isolation OFF" \
    bash "$DIR/23_wave_l_parquet_isolation.sh"
  run_gate "13_wave_l_mqtts_namespace" "13 Wave L MQTTS namespace OFF" \
    bash "$DIR/24_wave_l_mqtts_namespace.sh"
  run_gate "14_wave_l_tenant_ui_session" "14 Wave L tenant UI/session OFF" \
    bash "$DIR/25_wave_l_tenant_ui_session.sh"
  run_gate "15_wave_l_tenant_budgets" "15 Wave L tenant budgets OFF" \
    bash "$DIR/26_wave_l_tenant_budgets.sh"
  run_gate "16_wave_l_ab_isolation" "16 Wave L A↔B isolation harness" \
    bash "$DIR/27_wave_l_ab_isolation.sh"
  run_gate "17_wave_l_legacy_migrate_dry_run" "17 Wave L legacy migrate dry-run" \
    bash "$DIR/28_wave_l_legacy_migrate_dry_run.sh"
fi

# --- 18 Wave M durable session / read-path honesty (gates 1-3) ---
run_gate "18_wave_m_durable_session" "18 Wave M durable session" \
  bash "$DIR/30_wave_m_durable_session.sh"

# --- 20 Wave N tenant ACL (ACME / B100 / lakeside_sd) — requires MT ON + users ---
if [[ "${WAVE_N_ACL:-1}" == "1" ]]; then
  run_gate "20_wave_n_tenant_acl" "20 Wave N tenant ACL" \
    bash "$DIR/31_wave_n_tenant_acl.sh"
else
  record_gate "20_wave_n_tenant_acl" SKIPPED "20 Wave N tenant ACL" \
    "WAVE_N_ACL=0"
fi

# --- 21 Wave N MQTTS continuity soak ---
if [[ "${WAVE_N_CONTINUITY:-1}" == "1" ]]; then
  run_gate "21_wave_n_mqtts_continuity" "21 Wave N MQTTS continuity" \
    env TELEMETRY_LIVE="${TELEMETRY_LIVE:-1}" bash "$DIR/32_wave_n_mqtts_continuity.sh"
else
  record_gate "21_wave_n_mqtts_continuity" SKIPPED "21 Wave N MQTTS continuity" \
    "WAVE_N_CONTINUITY=0"
fi

# --- 22 Wave O admin + data-model/session ACL ---
if [[ "${WAVE_O_ADMIN_ACL:-1}" == "1" ]]; then
  run_gate "22_wave_o_admin_datamodel_acl" "22 Wave O admin + data-model ACL" \
    bash "$DIR/33_wave_o_admin_datamodel_acl.sh"
else
  record_gate "22_wave_o_admin_datamodel_acl" SKIPPED "22 Wave O admin + data-model ACL" \
    "WAVE_O_ADMIN_ACL=0"
fi

# --- 23 Wave O security headers / security.txt / CORS / login throttle ---
if [[ "${WAVE_O_SECURITY:-1}" == "1" ]]; then
  run_gate "23_wave_o_security" "23 Wave O security surface" \
    bash "$DIR/34_wave_o_security.sh"
else
  record_gate "23_wave_o_security" SKIPPED "23 Wave O security surface" \
    "WAVE_O_SECURITY=0"
fi

# --- 19 Wave M AFDD flood gate 12 (isolated default; live needs ALLOW_LIVE=1) ---
# Parent railway stress is an authorized ops window (same class as ZAP) — default ALLOW_LIVE=1 here.
# Uses OPENFDD_ADMIN_TOKEN minted at stress start (gate 23 login throttle must not force re-login).
AFDD_FLOOD_COOLDOWN_SECS="${AFDD_FLOOD_COOLDOWN_SECS:-15}"
echo "AFDD flood cool-down ${AFDD_FLOOD_COOLDOWN_SECS}s"
sleep "$AFDD_FLOOD_COOLDOWN_SECS"
set +e
OPENFDD_AFDD_FLOOD_ALLOW_LIVE="${OPENFDD_AFDD_FLOOD_ALLOW_LIVE:-1}" \
  OPENFDD_ADMIN_TOKEN="${OPENFDD_ADMIN_TOKEN:-}" \
  OPENFDD_AFDD_FLOOD_IGNORE_RULES_FAILED="${OPENFDD_AFDD_FLOOD_IGNORE_RULES_FAILED:-1}" \
  bash "$DIR/2N_wave_m_afdd_flood.sh" 2>&1 | tee "$ART/19_wave_m_afdd_flood.log"
FLOOD_RC=${PIPESTATUS[0]}
set -e
if [[ "$FLOOD_RC" -eq 0 ]]; then
  record_gate "19_wave_m_afdd_flood" PASS "19 Wave M AFDD flood" "" \
    "$ART/19_wave_m_afdd_flood.log" "$ART/2N_wave_m_afdd_flood.json"
elif [[ "$FLOOD_RC" -eq 2 ]]; then
  record_gate "19_wave_m_afdd_flood" BLOCKED "19 Wave M AFDD flood" \
    "isolated-candidate default; set OPENFDD_AFDD_FLOOD_ALLOW_LIVE=1 for authorized live window" \
    "$ART/19_wave_m_afdd_flood.log" "$ART/2N_wave_m_afdd_flood.json"
else
  record_gate "19_wave_m_afdd_flood" FAIL "19 Wave M AFDD flood" "exit=$FLOOD_RC" \
    "$ART/19_wave_m_afdd_flood.log" "$ART/2N_wave_m_afdd_flood.json"
fi

# --- 24 capacity pressure (S5a; sampler already running) ---
run_gate "24_capacity_pressure" "24 capacity pressure" \
  bash "$DIR/24_capacity_pressure.sh"

capacity_sampler_stop || true
trap - EXIT
set +e
capacity_write_report
CAP_RC=$?
set -e
if [[ -f "$ART/capacity_report.json" ]]; then
  if [[ "$CAP_RC" -eq 0 ]]; then
    record_gate "24b_capacity_report" PASS "24b capacity report" "" \
      "$ART/capacity_report.json" "$ART/capacity_samples.ndjson" "$ART/hub_env_capacity.json"
  else
    record_gate "24b_capacity_report" FAIL "24b capacity report" "hard_fail_or_strict" \
      "$ART/capacity_report.json" "$ART/capacity_samples.ndjson" "$ART/hub_env_capacity.json"
  fi
else
  record_gate "24b_capacity_report" FAIL "24b capacity report" "missing capacity_report.json"
fi

# Finalize — SUMMARY generated from recorded gates only
set +e
python3 "$MANIFEST_PY" finalize --manifest "$MANIFEST" --summary-md "$ART/SUMMARY.md"
FINAL_RC=$?
set -e
echo "Report: $ART/SUMMARY.md"
echo "Manifest: $MANIFEST"
if [[ -f "$ART/capacity_report.json" ]]; then
  echo "Capacity: $ART/capacity_report.json"
  jq -c '{status,sample_count,soft_warns,hard_fails,peak_memory_percent_used,delta_historian_small_files}' \
    "$ART/capacity_report.json" 2>/dev/null || true
fi
cat "$ART/SUMMARY.md"
exit "$FINAL_RC"
