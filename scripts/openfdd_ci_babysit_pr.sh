#!/usr/bin/env bash
# Babysit PR CI: poll every 30m for up to 6h; merge when green; start GHCR deep-sleep after merge.
set -euo pipefail

PR="${OPENFDD_BABYSIT_PR:-475}"
REPO="${OPENFDD_GH_REPO:-bbartling/open-fdd}"
INTERVAL="${OPENFDD_BABYSIT_INTERVAL_SEC:-1800}"
MAX_WAKES="${OPENFDD_BABYSIT_MAX_WAKES:-12}"
LOG="${OPENFDD_BABYSIT_LOG:-/tmp/openfdd_ci_babysit.log}"
ISSUE="${OPENFDD_GH_ISSUE:-429}"

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" | tee -a "$LOG"; }

pr_all_green() {
  local pending failed
  pending="$(gh pr checks "$PR" --repo "$REPO" 2>/dev/null | awk '$2 == "pending" {c++} END {print c+0}')"
  failed="$(gh pr checks "$PR" --repo "$REPO" 2>/dev/null | awk '$2 == "fail" {c++} END {print c+0}')"
  [[ "${pending:-0}" -eq 0 && "${failed:-0}" -eq 0 ]]
}

log "babysit start pr=$PR interval=${INTERVAL}s max_wakes=$MAX_WAKES"

for ((i = 1; i <= MAX_WAKES; i++)); do
  state="$(gh pr view "$PR" --repo "$REPO" --json state --jq '.state' 2>/dev/null || echo UNKNOWN)"
  if [[ "$state" == "MERGED" ]]; then
    log "PR already merged"
    exit 0
  fi

  if pr_all_green; then
    log "all checks green — merging PR #$PR"
    gh pr merge "$PR" --repo "$REPO" --squash --delete-branch >>"$LOG" 2>&1 || true
    sha="$(gh api repos/$REPO/commits/master --jq '.sha[0:7]' 2>/dev/null || echo unknown)"
    run_id="$(gh run list --repo "$REPO" --workflow "Publish Rust edge to GHCR" --branch master --limit 1 --json databaseId --jq '.[0].databaseId' 2>/dev/null || true)"
    gh issue comment "$ISSUE" --repo "$REPO" --body "**Product CI babysit** — PR #${PR} merged @ \`${sha}\`. GHCR run \`${run_id:-pending}\`. Bench: wait for NIGHTLY READY before deploy (3.2.13 PCAP gate)." >>"$LOG" 2>&1 || true
    if [[ -n "${run_id:-}" ]]; then
      OPENFDD_GHCR_RUN_ID="$run_id" OPENFDD_GH_MAX_WAKES=24 nohup ./scripts/openfdd_product_ghcr_deep_sleep.sh >>"$LOG" 2>&1 &
      log "started GHCR deep-sleep watcher run=$run_id pid=$!"
    fi
    exit 0
  fi

  failed="$(gh pr checks "$PR" --repo "$REPO" 2>/dev/null | awk '$2 == "fail" {print $1}' | head -5 | tr '\n' ' ' || true)"
  pending="$(gh pr checks "$PR" --repo "$REPO" 2>/dev/null | awk '$2 == "pending" {c++} END {print c+0}')"
  log "wake=$i pending=$pending failed=[${failed:-none}]"
  if [[ -n "${failed// /}" && "${pending:-0}" -eq 0 ]]; then
    gh issue comment "$ISSUE" --repo "$REPO" --body "**CI babysit wake $i/$MAX_WAKES** — PR #${PR} still failing: \`${failed}\`. Product iterating." >>"$LOG" 2>&1 || true
  fi

  [[ "$i" -lt "$MAX_WAKES" ]] && sleep "$INTERVAL"
done

log "babysit timeout after $MAX_WAKES wakes"
exit 2
