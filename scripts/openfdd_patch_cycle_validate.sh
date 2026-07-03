#!/usr/bin/env bash
# AI-agent-driven patch cycle validation — dynamic GH issues, restart-on-fail, zip + post results issue.
#
#   cd /home/ben/open-fdd && ./scripts/openfdd_patch_cycle_validate.sh
#
# Wait for GH Actions GHCR publish (user notifies), then:
#   OPENFDD_WAIT_FOR_GHCR=0 OPENFDD_GHCR_TAG=3.2.3 ./scripts/openfdd_patch_cycle_validate.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_bench_lib.sh
source "$ROOT/scripts/openfdd_bench_lib.sh"
# shellcheck source=scripts/openfdd_gh_scope_lib.sh
source "$ROOT/scripts/openfdd_gh_scope_lib.sh"

openfdd_bench_load_profile "$ROOT"

# Ensure all bench scripts executable (prior runs hit Permission denied on finalize)
chmod +x "$ROOT"/scripts/openfdd_*.sh 2>/dev/null || true

# Consolidated findings: workspace/reports/BENCH_VALIDATION_REPORT.md

TAG="${OPENFDD_GHCR_TAG:-${OPENFDD_EXPECT_VERSION:-3.2.3}}"
MAX_RESTARTS="${OPENFDD_MAX_RESTARTS:-2}"
RESTART_ON_FAIL="${OPENFDD_RESTART_ON_FAIL:-1}"
ATTEMPT=0
OVERALL=FAIL

if [[ "${OPENFDD_WAIT_FOR_GHCR:-0}" == "1" ]]; then
  echo "OPENFDD_WAIT_FOR_GHCR=1 — waiting for user/GH Actions signal. Set OPENFDD_WAIT_FOR_GHCR=0 to run." >&2
  exit 2
fi

run_once() {
  local attempt="$1"
  local RUN_TS PATCH_NAME PATCH_ROOT LOG_DIR ZIP_PATH RESULTS_ISSUE

  RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
  PATCH_NAME="open-fdd-${TAG}-patch-${RUN_TS}-a${attempt}"
  PATCH_ROOT="${OPENFDD_PATCH_DIR:-$ROOT/workspace/logs/patches/$PATCH_NAME}"
  LOG_DIR="$PATCH_ROOT/validation"
  ZIP_PATH="${ROOT}/workspace/logs/patches/${PATCH_NAME}.zip"

  rm -rf "$PATCH_ROOT" 2>/dev/null || true
  mkdir -p "$PATCH_ROOT" "$LOG_DIR"
  exec > >(tee -a "$PATCH_ROOT/overnight.log") 2>&1

  log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }
  log "=== Patch cycle attempt $attempt/$MAX_RESTARTS tag=$TAG ==="

  # Dynamic GH scope (issues change hourly)
  mkdir -p "$LOG_DIR/gh_scope"
  RESULTS_ISSUE="$(openfdd_gh_fetch_scope "$LOG_DIR/gh_scope/scope.json" 2>/dev/null || echo "${OPENFDD_RESULTS_ISSUE:-411}")"
  cp "$LOG_DIR/gh_scope/scope.json" "$PATCH_ROOT/gh_scope.json"
  log "Open issues/PRs fetched; results issue #$RESULTS_ISSUE"

  write_sequence_doc() {
    cat >"$PATCH_ROOT/EXPERT_TEST_SEQUENCE.md" <<EOF
# AI-agent patch cycle — Open-FDD ${TAG}

- **No git clone** — GHCR pull + bench scripts only
- Results issue: https://github.com/${OPENFDD_GITHUB_REPO:-bbartling/open-fdd}/issues/${RESULTS_ISSUE}
- README ref: ${OPENFDD_README_RAW_URL:-master README}

## Sequence (expert order)

| Step | What | Script |
|------|------|--------|
| A | Fetch open issues/PRs (read-only) | gh scope |
| B | AI bootstrap: .env, haystack, auth, README fetch | \`openfdd_env_bootstrap_validate.sh\` |
| C | Validate README + local agent prompts | \`openfdd_readme_agent_prompts_validate.sh\` |
| D | Docker health — **no error logs** | \`openfdd_docker_health_audit.sh\` |
| E | Pull edge + MCP sidecar images | docker pull |
| F | Driver gate (API discovery) | \`openfdd_drivers_validate.sh\` |
| G | **Step 3: 60×1min drivers** + fault rule change @ min 30; postbin once | \`openfdd_hour_driver_fault_test.sh\` |
| H | Semantic / RDF ([#406](https://github.com/bbartling/open-fdd/issues/406)) | \`openfdd_api_semantic_eval.sh\` |
| I | MCP sidecar stdio ([#411](https://github.com/bbartling/open-fdd/issues/411)) | \`openfdd_mcp_eval.sh\` |
| J | Rigorous + PDF | \`openfdd_drivers_rigorous_validate.sh\` |
| K | PCAP + ZAP matrix (direct + caddy-http + caddy-tls) | finalize + \`openfdd_zap_caddy_matrix.sh\` |

**On FAIL:** delete patch dir and restart from step A (max ${MAX_RESTARTS} attempts).
EOF
  }
  write_sequence_doc

  stage_prompts() {
    mkdir -p "$PATCH_ROOT"
    cp "$ROOT/workspace/reports/BENCH_VALIDATION_REPORT.md" "$PATCH_ROOT/" 2>/dev/null || true
    cp "$ROOT/workspace/bench/bench_profile.toml"* "$PATCH_ROOT/" 2>/dev/null || true
  }
  stage_prompts

  local FAIL=0
  run_phase() {
    local name="$1" dir="$2" script="$3"
    mkdir -p "$dir"
    log "Phase: $name"
    if "$ROOT/scripts/$script" | tee "$dir/run.log"; then
      log "PASS $name"
    else
      log "FAIL $name"
      FAIL=1
    fi
  }

  export OPENFDD_BOOTSTRAP_DIR="$LOG_DIR/bootstrap"
  if ! "$ROOT/scripts/openfdd_env_bootstrap_validate.sh" | tee "$LOG_DIR/bootstrap/run.log"; then FAIL=1; fi

  export OPENFDD_PROMPTS_DIR="$LOG_DIR/agent_prompts"
  if ! "$ROOT/scripts/openfdd_readme_agent_prompts_validate.sh" | tee "$LOG_DIR/agent_prompts/run.log"; then FAIL=1; fi
  cp -r "$LOG_DIR/agent_prompts/agent-prompts-fetched" "$PATCH_ROOT/" 2>/dev/null || true

  export OPENFDD_DOCKER_HEALTH_DIR="$LOG_DIR/docker_health"
  run_phase "docker-health" "$LOG_DIR/docker_health" "openfdd_docker_health_audit.sh" || FAIL=1

  if [[ "${OPENFDD_SKIP_PULL:-0}" != "1" ]]; then
    log "Pull edge ${OPENFDD_RUST_GHCR_IMAGE:-ghcr.io/bbartling/openfdd-edge-rust}:${TAG}"
    docker pull "${OPENFDD_RUST_GHCR_IMAGE:-ghcr.io/bbartling/openfdd-edge-rust}:${TAG}" 2>"$LOG_DIR/docker_pull_edge.err" || true
    docker pull "${OPENFDD_MCP_GHCR_IMAGE:-ghcr.io/bbartling/openfdd-mcp}:${TAG}" 2>"$LOG_DIR/docker_pull_mcp.err" || true
    if [[ -x "$ROOT/scripts/openfdd_rust_site_update.sh" ]]; then
      NEW_TAG="$TAG" OPENFDD_IMAGE_TAG="$TAG" "$ROOT/scripts/openfdd_rust_site_update.sh" 2>&1 | tee "$LOG_DIR/site_update.log" || true
    fi
  fi

  export OPENFDD_DRIVERS_VALIDATE_DIR="$LOG_DIR/drivers"
  export OPENFDD_REQUIRE_HAYSTACK=1
  export OPENFDD_EXPECT_VERSION="$TAG"
  run_phase "drivers" "$LOG_DIR/drivers" "openfdd_drivers_validate.sh" || FAIL=1

  export OPENFDD_HOUR_TEST_DIR="$LOG_DIR/hour_test"
  run_phase "hour-1m-drivers-fault-rule" "$LOG_DIR/hour_test" "openfdd_hour_driver_fault_test.sh" || FAIL=1

  export OPENFDD_SEMANTIC_EVAL_DIR="$LOG_DIR/semantic"
  run_phase "semantic-rdf" "$LOG_DIR/semantic" "openfdd_api_semantic_eval.sh" || FAIL=1
  cp -f "$LOG_DIR/semantic/wonky.txt" "$PATCH_ROOT/wonky.txt" 2>/dev/null || true

  export OPENFDD_MCP_EVAL_DIR="$LOG_DIR/mcp"
  run_phase "mcp-sidecar" "$LOG_DIR/mcp" "openfdd_mcp_eval.sh" || {
    [[ "${OPENFDD_EXPERT_REQUIRE_MCP:-0}" == "1" ]] && FAIL=1
  }

  export OPENFDD_DRIVERS_RIGOROUS_DIR="$LOG_DIR/rigorous"
  export OPENFDD_GENERATE_PDF=1
  run_phase "rigorous-pdf" "$LOG_DIR/rigorous" "openfdd_drivers_rigorous_validate.sh" || FAIL=1
  find "$LOG_DIR/rigorous" -name '*.pdf' -exec cp -f {} "$PATCH_ROOT/validation_report.pdf" \; 2>/dev/null || true

  if [[ "${OPENFDD_SKIP_FINALIZE:-0}" != "1" ]]; then
    export OPENFDD_FINALIZE_DIR="$LOG_DIR/finalize"
    export OPENFDD_SOAK_MINUTES=10
    export OPENFDD_PCAP_DURATION_SEC=600
    export OPENFDD_RUN_ZAP=1
    export OPENFDD_ZAP_CADDY_MATRIX=1
    run_phase "pcap-zap-caddy-matrix" "$LOG_DIR/finalize" "openfdd_soak_pcap_zap_finalize.sh" || FAIL=1
  fi

  # Issue post body
  cat >"$PATCH_ROOT/ISSUE_POST.md" <<EOF
## Open-FDD \`${TAG}\` — AI patch cycle validation (attempt ${attempt})

**Overall:** $([[ "$FAIL" -eq 0 ]] && echo PASS || echo **FAIL**)
**Results issue scope:** fetched live from [open issues](https://github.com/${OPENFDD_GITHUB_REPO:-bbartling/open-fdd}/issues)
**Patch dir:** \`${PATCH_ROOT}\`

| Phase | Result |
|-------|--------|
| Bootstrap / .env | $(jq -r 'if .ok then "PASS" else "FAIL" end' "$LOG_DIR/bootstrap/result.json" 2>/dev/null || echo ?) |
| Agent prompts | $(jq -r 'if .ok then "PASS" else "FAIL" end' "$LOG_DIR/agent_prompts/result.json" 2>/dev/null || echo ?) |
| Docker health | $(grep -q '^FAIL' "$LOG_DIR/docker_health/summary.txt" 2>/dev/null && echo FAIL || echo PASS) |
| Drivers | $(grep -q '^FAIL' "$LOG_DIR/drivers/summary.txt" 2>/dev/null && echo FAIL || echo PASS) |
| Hour test 1m + fault @30 | $(jq -r 'if .ok then "PASS" else "FAIL" end' "$LOG_DIR/hour_test/result.json" 2>/dev/null || echo ?) |
| Semantic / RDF | $(jq -r 'if .ok then "PASS" else "FAIL" end' "$LOG_DIR/semantic/result.json" 2>/dev/null || echo ?) |
| MCP sidecar | $(jq -r 'if .ok then "PASS" else "FAIL/SKIP" end' "$LOG_DIR/mcp/result.json" 2>/dev/null || echo ?) |
| PDF | $(test -f "$PATCH_ROOT/validation_report.pdf" && echo PASS || echo FAIL) |

### Open issues this cycle
$(jq -r '.open_issues[] | "- #\(.number) \(.title)"' "$PATCH_ROOT/gh_scope.json" 2>/dev/null || echo "see gh_scope.json")

### Wonky
\`\`\`
$(head -25 "$PATCH_ROOT/wonky.txt" 2>/dev/null || echo none)
\`\`\`

Zip attached locally: \`${ZIP_PATH}\`
EOF

  log "Creating zip"
  rm -f "$ZIP_PATH"
  (cd "$(dirname "$PATCH_ROOT")" && zip -rq "$ZIP_PATH" "$(basename "$PATCH_ROOT")" -x '*.pcap') || true

  if [[ "${OPENFDD_SKIP_POST:-0}" != "1" ]] && command -v gh >/dev/null 2>&1; then
    gh issue comment "$RESULTS_ISSUE" --repo "${OPENFDD_GITHUB_REPO:-bbartling/open-fdd}" \
      --body-file "$PATCH_ROOT/ISSUE_POST.md" | tee "$PATCH_ROOT/gh_comment.url" || true
  fi

  echo "$PATCH_ROOT" >"$ROOT/workspace/logs/patch_latest.dir"
  echo "$ZIP_PATH" >"$ROOT/workspace/logs/patch_latest.zip"

  [[ "$FAIL" -eq 0 ]]
}

while [[ "$ATTEMPT" -le "$MAX_RESTARTS" ]]; do
  ATTEMPT=$((ATTEMPT + 1))
  if run_once "$ATTEMPT"; then
    OVERALL=PASS
    break
  fi
  if [[ "$RESTART_ON_FAIL" != "1" || "$ATTEMPT" -gt "$MAX_RESTARTS" ]]; then
    OVERALL=FAIL
    break
  fi
  echo "[restart] attempt $ATTEMPT failed — restarting from scratch in 10s" >&2
  sleep 10
done

echo "=== PATCH CYCLE $OVERALL after $ATTEMPT attempt(s) ==="
[[ "$OVERALL" == "PASS" ]]
