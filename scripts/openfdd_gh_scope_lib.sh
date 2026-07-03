#!/usr/bin/env bash
# Read-only GitHub scope for patch cycle — issues/PRs via gh (no git clone).
set -euo pipefail

OPENFDD_GITHUB_REPO="${OPENFDD_GITHUB_REPO:-bbartling/open-fdd}"

openfdd_gh_require() {
  command -v gh >/dev/null 2>&1 || {
    echo "ERROR: gh CLI required for dynamic issue/PR scope" >&2
    return 1
  }
  command -v jq >/dev/null 2>&1 || {
    echo "ERROR: jq required" >&2
    return 1
  }
}

# Writes scope JSON: open issues, open PRs, resolved results issue number.
openfdd_gh_fetch_scope() {
  local out_file="${1:?output json path}"
  local results_issue="${OPENFDD_RESULTS_ISSUE:-}"

  openfdd_gh_require || return 1
  mkdir -p "$(dirname "$out_file")"

  gh issue list --repo "$OPENFDD_GITHUB_REPO" --state open --limit 50 \
    --json number,title,labels,updatedAt >"${out_file}.issues.json" 2>/dev/null || echo '[]' >"${out_file}.issues.json"

  gh pr list --repo "$OPENFDD_GITHUB_REPO" --state open --limit 50 \
    --json number,title,headRefName,baseRefName,updatedAt >"${out_file}.prs.json" 2>/dev/null || echo '[]' >"${out_file}.prs.json"

  # Recent merged PRs touching 3.2.x (read-only context)
  gh pr list --repo "$OPENFDD_GITHUB_REPO" --state merged --limit 30 \
    --json number,title,headRefName,mergedAt >"${out_file}.prs_merged.json" 2>/dev/null || echo '[]' >"${out_file}.prs_merged.json"

  if [[ -z "$results_issue" ]]; then
    results_issue="$(jq -r '[.[] | select(.title | test("test results"; "i"))] | sort_by(.updatedAt) | last | .number // empty' \
      "${out_file}.issues.json" 2>/dev/null || true)"
  fi
  results_issue="${results_issue:-411}"

  jq -nc \
    --arg repo "$OPENFDD_GITHUB_REPO" \
    --argjson results_issue "$results_issue" \
    --arg fetched "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --slurpfile issues "${out_file}.issues.json" \
    --slurpfile prs "${out_file}.prs.json" \
    --slurpfile merged "${out_file}.prs_merged.json" \
    '{
      repo: $repo,
      fetched_at: $fetched,
      results_issue: $results_issue,
      open_issues: $issues[0],
      open_prs: $prs[0],
      merged_prs_recent: $merged[0]
    }' >"$out_file"

  printf '%s' "$results_issue"
}

openfdd_gh_fetch_raw() {
  local url="$1" dest="$2"
  curl -fsSL "$url" -o "$dest" 2>/dev/null || return 1
}
