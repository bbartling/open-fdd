#!/usr/bin/env bash
# Full rigorous bench run: hour test (fault @30) → semantic → rigorous/PDF → ZAP matrix → BACnet daemon.
#
#   cd /home/ben/open-fdd && ./scripts/openfdd_rigorous_full_run.sh
#
# Env:
#   OPENFDD_HOUR_REQUIRE_HAYSTACK=0   skip haystack gate when creds missing
#   OPENFDD_HOUR_REQUIRE_JSON=0         skip json-api gate when not configured
#   OPENFDD_START_BACNET_DAEMON=1       ensure 1m poll daemon running (default 1, starts before hour test)
#   OPENFDD_ALWAYS_POLL=1                 start daemon at run start (default 1)
#   OPENFDD_SKIP_HOUR=0 OPENFDD_SKIP_ZAP=0
#   OPENFDD_SKIP_PRECHECK=1           resume after hour test complete
#   OPENFDD_RIGOROUS_RUN_DIR=...      reuse existing artifact dir
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_bench_lib.sh
source "$ROOT/scripts/openfdd_bench_lib.sh"

openfdd_bench_load_profile "$ROOT"
openfdd_bench_apply_validation_gates "$ROOT"
chmod +x "$ROOT"/scripts/openfdd_*.sh 2>/dev/null || true

RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_DIR="${OPENFDD_RIGOROUS_RUN_DIR:-$ROOT/workspace/logs/rigorous_full_${RUN_TS}}"
mkdir -p "$LOG_DIR"
echo "$LOG_DIR" >"$ROOT/workspace/logs/rigorous_full_latest.dir"
exec > >(tee -a "$LOG_DIR/rigorous_full.log") 2>&1

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }
RUN_FAIL=0

log "=== Rigorous full run → $LOG_DIR ==="

# Phase -1: always attempt latest GHCR pull + site update (historian restore default)
if [[ "${OPENFDD_SKIP_PULL:-0}" != "1" && "${OPENFDD_SKIP_PRECHECK:-0}" != "1" ]]; then
  log "=== Phase -1: pull latest GHCR + site update ==="
  if "$ROOT/scripts/openfdd_bench_pull_latest.sh" 2>&1 | tee "$LOG_DIR/ghcr_pull.log"; then
    log "PASS ghcr pull"
    # shellcheck disable=SC1091
    [[ -f "$ROOT/workspace/logs/ghcr_pull_latest.env" ]] && source "$ROOT/workspace/logs/ghcr_pull_latest.env"
    export OPENFDD_IMAGE_TAG OPENFDD_GHCR_TAG OPENFDD_MCP_GHCR_TAG
    REQUIRE_BACKUP=0 SKIP_DOCKER_MAINTENANCE=1 \
      OPENFDD_IMAGE_TAG="${OPENFDD_IMAGE_TAG:-nightly}" \
      "$ROOT/scripts/openfdd_rust_site_update.sh" 2>&1 | tee "$LOG_DIR/site_update.log" || {
      log "WARN site update failed after pull — continuing if stack healthy"
    }
  else
    log "FAIL ghcr pull latest — see ghcr_pull.log (GHCR manifest or auth); continuing on running stack if healthy"
    curl -fsS http://127.0.0.1:8080/api/health | jq . | tee "$LOG_DIR/health_after_pull_fail.json" || true
  fi
fi

# Phase 0: README prompts, MCP, RBAC, historian-restore smoke (skip on resume)
if [[ "${OPENFDD_RUN_PREFLIGHT:-1}" == "1" && "${OPENFDD_SKIP_PRECHECK:-0}" != "1" ]]; then
  log "=== Phase 0: preflight (README prompts, MCP, RBAC) ==="
  export OPENFDD_PROMPTS_DIR="$LOG_DIR/preflight/prompts"
  export OPENFDD_MCP_EVAL_DIR="$LOG_DIR/preflight/mcp"
  export OPENFDD_RBAC_DIR="$LOG_DIR/preflight/rbac"
  mkdir -p "$LOG_DIR/preflight"
  if "$ROOT/scripts/openfdd_readme_agent_prompts_validate.sh" | tee "$LOG_DIR/preflight/prompts.log"; then
    log "PASS readme prompts"
  else
    log "WARN readme prompts fail"
    RUN_FAIL=1
  fi
  if "$ROOT/scripts/openfdd_mcp_eval.sh" | tee "$LOG_DIR/preflight/mcp.log"; then
    log "PASS mcp eval"
  else
    log "WARN mcp eval fail"
    RUN_FAIL=1
  fi
  if "$ROOT/scripts/openfdd_auth_rbac_validate.sh" | tee "$LOG_DIR/preflight/rbac.log"; then
    log "PASS rbac eval"
  else
    log "WARN rbac eval fail"
    RUN_FAIL=1
  fi
fi

# Pre-check BACnet
if [[ "${OPENFDD_SKIP_PRECHECK:-0}" != "1" ]]; then
export OPENFDD_DRIVERS_VALIDATE_DIR="$LOG_DIR/drivers_precheck"
export OPENFDD_EXPECT_VERSION="${OPENFDD_EXPECT_VERSION:-3.2.3}"
export OPENFDD_SKIP_PULL=1
BACNET_OK=0
if "$ROOT/scripts/openfdd_drivers_validate.sh" | tee "$LOG_DIR/drivers_precheck.log"; then
  BACNET_OK=1
elif grep -q 'PASS  bacnet' "$LOG_DIR/drivers_precheck/summary.txt" 2>/dev/null; then
  BACNET_OK=1
  log "WARN drivers gate partial fail but BACnet PASS — continuing"
else
  log "FAIL BACnet not green — abort before hour test"
  exit 1
fi
else
  BACNET_OK=1
  log "SKIP precheck (resume)"
fi

# Persistent 1m OT polling — start immediately and keep running through + after tests
if [[ "${OPENFDD_START_BACNET_DAEMON:-1}" == "1" && "${OPENFDD_ALWAYS_POLL:-1}" == "1" && "$BACNET_OK" == "1" \
    && "${OPENFDD_SKIP_PRECHECK:-0}" != "1" ]]; then
  log "=== Start persistent 1m poll daemon (runs through entire validation) ==="
  "$ROOT/scripts/openfdd_bacnet_poll_daemon.sh" stop 2>/dev/null || true
  "$ROOT/scripts/openfdd_bacnet_poll_daemon.sh" start | tee "$LOG_DIR/bacnet_daemon_start.log"
  "$ROOT/scripts/openfdd_bacnet_poll_daemon.sh" status | tee -a "$LOG_DIR/bacnet_daemon_start.log"
fi

export OPENFDD_HOUR_REQUIRE_HAYSTACK="${OPENFDD_HOUR_REQUIRE_HAYSTACK:-}"
export OPENFDD_HOUR_REQUIRE_JSON="${OPENFDD_HOUR_REQUIRE_JSON:-}"
openfdd_bench_apply_validation_gates "$ROOT"
log "Hour gates: require_haystack=${OPENFDD_HOUR_REQUIRE_HAYSTACK} require_json=${OPENFDD_HOUR_REQUIRE_JSON} (haystack_pass_configured=$(openfdd_bench_haystack_pass_configured "$ROOT" && echo yes || echo no))"

if [[ "${OPENFDD_SKIP_HOUR:-0}" != "1" ]]; then
  log "=== Phase 1: hour test (${OPENFDD_HOUR_TEST_MINUTES:-60}m, fault @ ${OPENFDD_FAULT_RULE_CHANGE_MINUTE:-30}) ==="
  export OPENFDD_HOUR_TEST_DIR="$LOG_DIR/hour_test"
  if "$ROOT/scripts/openfdd_hour_driver_fault_test.sh" | tee "$LOG_DIR/hour_test.log"; then
    hour_rc=0
  else
    hour_rc=$?
  fi
  if [[ "$hour_rc" -eq 0 ]]; then
    log "PASS hour test"
  else
    log "FAIL hour test (exit $hour_rc)"
    RUN_FAIL=1
  fi
else
  log "SKIP hour test"
fi

log "=== Phase 2: semantic / RDF / SPARQL probes ==="
export OPENFDD_SEMANTIC_EVAL_DIR="$LOG_DIR/semantic"
if "$ROOT/scripts/openfdd_api_semantic_eval.sh" | tee "$LOG_DIR/semantic.log"; then
  log "PASS semantic"
else
  log "WARN semantic fail (RDF 404 expected until #406)"
fi

log "=== Phase 3: rigorous drivers + PDF ==="
export OPENFDD_DRIVERS_RIGOROUS_DIR="$LOG_DIR/rigorous"
export OPENFDD_GENERATE_PDF=1
if "$ROOT/scripts/openfdd_drivers_rigorous_validate.sh" | tee "$LOG_DIR/rigorous.log"; then
  log "PASS rigorous"
else
  log "WARN rigorous partial fail (artifact capture)"
  RUN_FAIL=1
fi

if [[ "${OPENFDD_SKIP_ZAP:-0}" != "1" ]]; then
  log "=== Phase 4: soak + PCAP + ZAP caddy matrix ==="
  export OPENFDD_FINALIZE_DIR="$LOG_DIR/finalize"
  export OPENFDD_SOAK_MINUTES="${OPENFDD_SOAK_MINUTES:-10}"
  export OPENFDD_PCAP_DURATION_SEC="${OPENFDD_PCAP_DURATION_SEC:-600}"
  export OPENFDD_RUN_ZAP=1
  export OPENFDD_ZAP_CADDY_MATRIX=1
  if "$ROOT/scripts/openfdd_soak_pcap_zap_finalize.sh" | tee "$LOG_DIR/finalize.log"; then
    log "PASS finalize/ZAP"
  else
    log "FAIL finalize/ZAP"
    RUN_FAIL=1
  fi
else
  log "SKIP ZAP/finalize"
fi

if [[ "${OPENFDD_START_BACNET_DAEMON:-1}" == "1" && "$BACNET_OK" == "1" ]]; then
  log "=== Ensure poll daemon still running after validation ==="
  "$ROOT/scripts/openfdd_bacnet_poll_daemon.sh" status | tee "$LOG_DIR/bacnet_daemon_final.log" \
    || "$ROOT/scripts/openfdd_bacnet_poll_daemon.sh" start | tee "$LOG_DIR/bacnet_daemon_final.log"
fi

jq -nc \
  --arg ts "$RUN_TS" --arg dir "$LOG_DIR" --argjson fail "$RUN_FAIL" --argjson bacnet_daemon "$BACNET_OK" \
  --slurpfile hour "$LOG_DIR/hour_test/result.json" \
  --slurpfile fin "$LOG_DIR/finalize/finalize_result.json" \
  '{
    timestamp_utc:$ts, artifact_dir:$dir, bacnet_ok:$bacnet_daemon,
    hour_test: ($hour[0] // {}), finalize: ($fin[0] // {}),
    bacnet_daemon_started: $bacnet_daemon, ok: ($fail == 0)
  }' >"$LOG_DIR/result.json" 2>/dev/null || \
  jq -nc --arg dir "$LOG_DIR" --argjson fail "$RUN_FAIL" '{artifact_dir:$dir,ok:($fail==0)}' >"$LOG_DIR/result.json"

echo "$LOG_DIR" >"$ROOT/workspace/logs/rigorous_full_latest.dir"
log "=== RIGOROUS FULL RUN DONE fail=$RUN_FAIL artifact=$LOG_DIR ==="

if [[ -x "$ROOT/scripts/openfdd_bench_consolidated_report.sh" ]]; then
  OPENFDD_RIGOROUS_RUN_DIR="$LOG_DIR" "$ROOT/scripts/openfdd_bench_consolidated_report.sh" \
    | tee "$LOG_DIR/consolidated_report.log" || true
fi

[[ "$RUN_FAIL" -eq 0 ]]
