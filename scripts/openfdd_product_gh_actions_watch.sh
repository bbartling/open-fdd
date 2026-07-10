#!/usr/bin/env bash
# Product-agent GH Actions gate for master (WSL). Exit 0 = all green on HEAD; 1 = failure; 2 = pending.
set -euo pipefail

REPO="${OPENFDD_GH_REPO:-bbartling/open-fdd}"
BRANCH="${OPENFDD_GH_BRANCH:-master}"

HEAD="$(gh api "repos/${REPO}/commits/${BRANCH}" --jq '.sha' | tr -d '"')"
HEAD7="${HEAD:0:7}"
MSG="$(gh api "repos/${REPO}/commits/${BRANCH}" --jq '.commit.message' | head -1 | tr -d '"' | cut -c1-72)"

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
    --json conclusion,status,headSha,url,databaseId,createdAt,updatedAt \
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
  echo "GH_ACTIONS_FAIL master@${HEAD7} ${MSG}"
  printf '  FAIL %s\n' "${failures[@]}"
  echo 'AGENT_LOOP_WAKE_GH_ACTIONS {"prompt":"GH Actions failure on bbartling/open-fdd master. Inspect failing workflow logs with gh run view, fix code or re-dispatch, merge if needed. Redeploy Pages/GHCR when fixed. Stay silent when all workflows success on HEAD."}'
  exit 1
fi

if ((${#pending[@]} > 0)); then
  # Pending — no wake; product stays silent until next tick or failure.
  exit 2
fi

# All green on HEAD — silent success (no sentinel).
exit 0
