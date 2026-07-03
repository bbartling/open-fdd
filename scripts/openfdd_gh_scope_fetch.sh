#!/usr/bin/env bash
# Fetch open issues + PRs (read-only) for patch cycle scope.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_gh_scope_lib.sh
source "$ROOT/scripts/openfdd_gh_scope_lib.sh"

LOG_DIR="${OPENFDD_GH_SCOPE_DIR:-$ROOT/workspace/logs/gh_scope_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$LOG_DIR"

issue="$(openfdd_gh_fetch_scope "$LOG_DIR/scope.json")"
echo "Results issue: #$issue"
echo "Scope: $LOG_DIR/scope.json"
jq '{open_issues: [.open_issues[] | {number,title}], open_prs: [.open_prs[] | {number,title,head}], results_issue}' \
  "$LOG_DIR/scope.json"
