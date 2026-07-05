#!/usr/bin/env bash
# Product-agent GH Actions gate for master (WSL). Exit 0 = all green on HEAD; 1 = failure; 2 = pending.
set -euo pipefail

REPO="${OPENFDD_GH_REPO:-bbartling/open-fdd}"
BRANCH="${OPENFDD_GH_BRANCH:-master}"

HEAD="$(gh api "repos/${REPO}/commits/${BRANCH}" --jq '.sha' | tr -d '"')"
HEAD7="${HEAD:0:7}"

WORKFLOWS=(
  "rust-ci.yml"
  "rust-ghcr.yml"
  "security.yml"
  "appsec.yml"
  "docs-pages.yml"
)

failures=()
pending=()

check_workflow() {
  local wf="$1"
  gh run list --repo "$REPO" --workflow "$wf" --branch "$BRANCH" --limit 15 \
    --json conclusion,status,headSha,url \
    -q "[.[] | select(.headSha == \"${HEAD}\")][0]"
}

for wf in "${WORKFLOWS[@]}"; do
  run="$(check_workflow "$wf")"
  if [[ -z "$run" || "$run" == "null" ]]; then
    pending+=("$wf:not_started")
    continue
  fi
  status="$(echo "$run" | jq -r '.status')"
  conclusion="$(echo "$run" | jq -r '.conclusion // ""')"
  url="$(echo "$run" | jq -r '.url')"
  if [[ "$conclusion" == "failure" || "$conclusion" == "cancelled" ]]; then
    failures+=("${wf}|${conclusion}|${url}")
  elif [[ "$status" != "completed" ]]; then
    pending+=("${wf}:${status}")
  elif [[ "$conclusion" != "success" && "$conclusion" != "skipped" && "$conclusion" != "neutral" ]]; then
    failures+=("${wf}|${conclusion:-unknown}|${url}")
  fi
done

if ((${#failures[@]} > 0)); then
  echo "GH_ACTIONS_FAIL master@${HEAD7}"
  printf '  FAIL %s\n' "${failures[@]}"
  echo 'AGENT_LOOP_WAKE_GH_ACTIONS {"prompt":"GH Actions failure on bbartling/open-fdd master. Fix and merge."}'
  exit 1
fi

if ((${#pending[@]} > 0)); then
  exit 2
fi

exit 0
