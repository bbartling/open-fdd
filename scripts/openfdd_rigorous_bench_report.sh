#!/usr/bin/env bash
# Rigorous bench report → workspace/reports/REV_330_RIGOROUS_TEST_REPORT.md
#
#   cd /home/ben/open-fdd && ./scripts/openfdd_rigorous_bench_report.sh
#
# Env:
#   OPENFDD_BENCH_TAG=nightly|beta|3.3.0-beta.1   deployed GHCR tag (default nightly)
#   OPENFDD_BENCH_POLL_CYCLES=5                     validation cycles @ 60s (daemon stays running)
#   OPENFDD_BENCH_SKIP_MCP=1 OPENFDD_BENCH_SKIP_RBAC=1 OPENFDD_BENCH_SKIP_FRONTEND=1
#   OPENFDD_BENCH_SKIP_PULL=1                       skip ghcr pull phase
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_auth_lib.sh
source "$ROOT/scripts/openfdd_auth_lib.sh"
# shellcheck source=scripts/openfdd_bench_lib.sh
source "$ROOT/scripts/openfdd_bench_lib.sh"
openfdd_bench_load_profile "$ROOT" || true

TAG="${OPENFDD_BENCH_TAG:-${OPENFDD_IMAGE_TAG:-nightly}}"
POLL_CYCLES="${OPENFDD_BENCH_POLL_CYCLES:-5}"
POLL_INTERVAL="${OPENFDD_DRIVER_POLL_INTERVAL_SEC:-60}"
ISSUE="${OPENFDD_RESULTS_ISSUE:-429}"
RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
ART="$ROOT/workspace/logs/rigorous_bench_${RUN_TS}"
REPORT="$ROOT/workspace/reports/REV_330_RIGOROUS_TEST_REPORT.md"
mkdir -p "$ART" "$(dirname "$REPORT")"

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$ART/run.log"; }

run_phase() {
  local name="$1"; shift
  log "=== $name ==="
  if "$@" >"$ART/${name}.log" 2>&1; then
    echo "PASS" >"$ART/${name}.status"
    log "PASS $name"
  else
    echo "FAIL" >"$ART/${name}.status"
    log "FAIL $name (see $ART/${name}.log)"
  fi
}

log "rigorous bench start tag=$TAG cycles=$POLL_CYCLES issue=#$ISSUE"

if [[ "${OPENFDD_BENCH_SKIP_PULL:-0}" != "1" ]]; then
  run_phase ghcr_pull "$ROOT/scripts/openfdd_bench_pull_latest.sh"
  # shellcheck disable=SC1091
  [[ -f "$ROOT/workspace/logs/ghcr_pull_latest.env" ]] && source "$ROOT/workspace/logs/ghcr_pull_latest.env"
  TAG="${OPENFDD_IMAGE_TAG:-$TAG}"
  NEW_TAG="$TAG" OPENFDD_RESTORE_HISTORIAN_AFTER_UPDATE=1 REQUIRE_BACKUP=0 \
    "$ROOT/scripts/openfdd_rust_site_update.sh" 2>&1 | tee "$ART/site_update.log" || true
fi

# Permanent poll daemon — production-like (unlimited cycles)
"$ROOT/scripts/openfdd_bacnet_poll_daemon.sh" stop 2>/dev/null || true
OPENFDD_BACNET_DAEMON_MAX_CYCLES=0 "$ROOT/scripts/openfdd_bacnet_poll_daemon.sh" start | tee "$ART/poll_daemon_start.log"

export OPENFDD_EXPECT_VERSION="$TAG"
export OPENFDD_DRIVERS_VALIDATE_DIR="$ART/drivers_validate"
export OPENFDD_POLL_VALIDATE_DIR="$ART/polling_feather"
export OPENFDD_POLL_VALIDATE_CYCLES="$POLL_CYCLES"
export OPENFDD_POLL_VALIDATE_INTERVAL_SEC="$POLL_INTERVAL"
export OPENFDD_SEMANTIC_EVAL_DIR="$ART/semantic_eval"
export OPENFDD_RBAC_DIR="$ART/rbac_eval"
export OPENFDD_MCP_EVAL_DIR="$ART/mcp_eval"

run_phase drivers_validate "$ROOT/scripts/openfdd_drivers_validate.sh"
run_phase polling_feather "$ROOT/scripts/openfdd_polling_feather_validate.sh"
run_phase semantic_eval "$ROOT/scripts/openfdd_api_semantic_eval.sh"
[[ "${OPENFDD_BENCH_SKIP_RBAC:-0}" != "1" ]] && run_phase rbac_eval "$ROOT/scripts/openfdd_auth_rbac_validate.sh"
[[ "${OPENFDD_BENCH_SKIP_MCP:-0}" != "1" ]] && run_phase mcp_eval "$ROOT/scripts/openfdd_mcp_eval.sh"

if [[ "${OPENFDD_BENCH_SKIP_FRONTEND:-0}" != "1" && -x "$ROOT/tests/selenium/openfdd_frontend_rigorous.sh" ]]; then
  export OPENFDD_FRONTEND_ARTIFACT_DIR="$ART/frontend_rigorous"
  run_phase frontend_rigorous "$ROOT/tests/selenium/openfdd_frontend_rigorous.sh"
fi

# FDD SQL soak when polling path is green
if [[ "${OPENFDD_BENCH_SKIP_FDD_SOAK:-0}" != "1" ]]; then
  export OPENFDD_SOAK_DIR="$ART/fdd_soak"
  export OPENFDD_SOAK_MINUTES="${OPENFDD_BENCH_FDD_SOAK_MINUTES:-10}"
  run_phase fdd_soak "$ROOT/scripts/openfdd_stores_fdd_soak.sh"
fi

BASE="${OPENFDD_API_BASE:-http://127.0.0.1:8080}"
COMMISSION="${OPENFDD_COMMISSION_BASE:-http://127.0.0.1:9091}"
AUTH="$ROOT/workspace/auth.env.local"
TOKEN="$(openfdd_auth_login_token "$BASE" "$AUTH" integrator)"
openfdd_bench_api GET "$BASE" "/api/health" "$TOKEN" | jq . >"$ART/health.json"
openfdd_bench_historian_store_snapshot "$BASE" "$TOKEN" "$ROOT" | jq . >"$ART/historian.json"
openfdd_bench_live_ot_poll "$BASE" "$COMMISSION" "$TOKEN" "$ROOT" | jq . >"$ART/live_ot.json"
openfdd_bench_api GET "$BASE" "/api/fdd-rules" "$TOKEN" | jq . >"$ART/fdd_rules.json"

VERSION="$(jq -r '.version // "?"' "$ART/health.json")"
IMAGE_TAG="$(jq -r '.image_tag // "?"' "$ART/health.json")"
HIST_ROWS="$(jq -r '.api_row_count // 0' "$ART/historian.json")"
FEATHER="$(jq -r '.feather_present // false' "$ART/historian.json")"
LIVE_OK="$(jq -r '.ok // false' "$ART/live_ot.json")"
DAEMON_PID="$(cat "$ROOT/workspace/logs/bacnet_poll_daemon/daemon.pid" 2>/dev/null || echo none)"

# Ensure daemon still running
"$ROOT/scripts/openfdd_bacnet_poll_daemon.sh" status | tee "$ART/poll_daemon_final.log" \
  || OPENFDD_BACNET_DAEMON_MAX_CYCLES=0 "$ROOT/scripts/openfdd_bacnet_poll_daemon.sh" start

cat >"$REPORT" <<EOF
# Open-FDD rigorous bench report — ${TAG}

**Generated:** $(date -u +%Y-%m-%dT%H:%M:%SZ) · **Bench:** \`${ROOT}\` · **GHCR tag:** \`${TAG}\`  
**Running version:** ${VERSION} · **image_tag:** ${IMAGE_TAG}  
**GitHub tracking:** [#${ISSUE}](https://github.com/bbartling/open-fdd/issues/${ISSUE})  
**Artifact dir:** \`${ART}\`  
**Poll daemon:** pid \`${DAEMON_PID}\` · **${POLL_INTERVAL}s** · **permanent (production-like)**

## Release channels ([README](https://github.com/bbartling/open-fdd/blob/master/README.md))

| Channel | Tag | This run |
|---------|-----|----------|
| Nightly | \`:nightly\` | $(if [[ "$TAG" == "nightly" || "$TAG" == sha-* ]]; then echo "**yes**"; else echo no; fi) |
| Beta | \`:beta\` / \`3.3.0-beta.N\` | $(if [[ "$TAG" == *beta* || "$TAG" == "beta" ]]; then echo "**yes**"; else echo no; fi) |
| Stable | \`:latest\` | $(if [[ "$TAG" == "latest" ]]; then echo yes; else echo "not yet published"; fi) |

## Phase status

| Phase | Status |
|-------|--------|
| ghcr_pull | $(cat "$ART/ghcr_pull.status" 2>/dev/null || echo SKIP) |
| drivers_validate | $(cat "$ART/drivers_validate.status" 2>/dev/null || echo SKIP) |
| polling_feather | $(cat "$ART/polling_feather.status" 2>/dev/null || echo SKIP) |
| semantic_eval | $(cat "$ART/semantic_eval.status" 2>/dev/null || echo SKIP) |
| rbac_eval | $(cat "$ART/rbac_eval.status" 2>/dev/null || echo SKIP) |
| mcp_eval | $(cat "$ART/mcp_eval.status" 2>/dev/null || echo SKIP) |
| frontend_rigorous | $(cat "$ART/frontend_rigorous.status" 2>/dev/null || echo SKIP) |
| fdd_soak (SQL + historian growth) | $(cat "$ART/fdd_soak.status" 2>/dev/null || echo SKIP) |

## Key metrics

| Metric | Value |
|--------|-------|
| Live OT reads | $(if [[ "$LIVE_OK" == "true" ]]; then echo PASS; else echo FAIL; fi) |
| Historian API rows | ${HIST_ROWS} |
| Feather store | ${FEATHER} |
| Poll daemon | $(cat "$ART/poll_daemon_final.log" 2>/dev/null | head -1 || echo unknown) |

## Open issues (patch cycle)

- #429 — bench sign-off gate
- #430–#435, #437 — FIX backlog (ZAP #435, Selenium #434, oxigraph #437, etc.)

## Re-run

\`\`\`bash
cd ${ROOT}
OPENFDD_BENCH_TAG=nightly OPENFDD_BENCH_POLL_CYCLES=5 ./scripts/openfdd_rigorous_bench_report.sh
# Full matrix (hour test + ZAP when ready):
OPENFDD_SKIP_ZAP=0 ./scripts/openfdd_rigorous_full_run.sh
\`\`\`

**Policy:** Leave \`openfdd_bacnet_poll_daemon.sh\` running after every test. Use \`run-for N\` only inside a single phase when bounded cycles are required.

EOF

echo "$ART" >"$ROOT/workspace/logs/rigorous_bench_latest.dir"
log "Wrote $REPORT"
echo "$REPORT"
