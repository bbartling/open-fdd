#!/usr/bin/env bash
# Deep-sleep GHCR gate: one API call per wake; exit 0 + #429 comment when :nightly published.
# Usage: OPENFDD_GHCR_RUN_ID=28815109155 ./scripts/openfdd_product_ghcr_deep_sleep.sh
set -euo pipefail

RUN_ID="${OPENFDD_GHCR_RUN_ID:?set OPENFDD_GHCR_RUN_ID}"
REPO="${OPENFDD_GH_REPO:-bbartling/open-fdd}"
ISSUE="${OPENFDD_GH_ISSUE:-429}"
INTERVAL="${OPENFDD_GH_SLEEP_SEC:-1800}"
MAX_WAKES="${OPENFDD_GH_MAX_WAKES:-48}"
LOG="${OPENFDD_GH_SLEEP_LOG:-/tmp/openfdd_ghcr_deep_sleep.log}"
PIDFILE="${OPENFDD_GH_SLEEP_PIDFILE:-/tmp/openfdd_ghcr_deep_sleep.pid}"

if [[ -f "$PIDFILE" ]]; then
  old="$(cat "$PIDFILE" 2>/dev/null || true)"
  if [[ -n "$old" ]] && kill -0 "$old" 2>/dev/null; then
    exit 0
  fi
fi
echo $$ >"$PIDFILE"
trap 'rm -f "$PIDFILE"' EXIT

echo "deep_sleep start run=$RUN_ID interval=${INTERVAL}s $(date -u +%Y-%m-%dT%H:%M:%SZ)" >>"$LOG"

for ((i = 1; i <= MAX_WAKES; i++)); do
  con="$(gh run view "$RUN_ID" --repo "$REPO" --json conclusion --jq '.conclusion // empty' 2>>"$LOG" || true)"
  echo "wake=$i $(date -u +%Y-%m-%dT%H:%M:%SZ) conclusion=${con:-pending}" >>"$LOG"
  case "$con" in
  success)
    gh issue comment "$ISSUE" --repo "$REPO" --body "**NIGHTLY READY** — GHCR run ${RUN_ID} success. Bench: \`OPENFDD_IMAGE_TAG=nightly ./scripts/openfdd_stack_up.sh standalone\` then \`docs/agent/linux-edge-tester-nightly-retest-prompt.md\`." >>"$LOG" 2>&1 || true
    exit 0
    ;;
  failure | cancelled)
    gh issue comment "$ISSUE" --repo "$REPO" --body "**GHCR FAIL** run ${RUN_ID} (${con}). Product wake." >>"$LOG" 2>&1 || true
    exit 1
    ;;
  esac
  sleep "$INTERVAL"
done
echo "deep_sleep timeout wakes=$MAX_WAKES" >>"$LOG"
exit 2
