#!/usr/bin/env bash
# Fail PRs that touch protected cookbooks/docs without an explicit bypass.
# Bypass: include [docs-guard-bypass] in the most recent commit message on the PR tip.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BASE_REF="${DOCS_GUARD_BASE:-origin/master}"
if ! git rev-parse --verify "$BASE_REF" >/dev/null 2>&1; then
  BASE_REF="origin/main"
fi
if ! git rev-parse --verify "$BASE_REF" >/dev/null 2>&1; then
  echo "docs-guard: no base ref (origin/master or origin/main); skipping"
  exit 0
fi

PROTECTED=(
  "docs/rules/"
  "openfdd_agent_spec/docs/EXPRESSION_RULE_COOKBOOK.md"
)

mapfile -t CHANGED < <(git diff --name-only "${BASE_REF}...HEAD" 2>/dev/null || true)
if [[ ${#CHANGED[@]} -eq 0 ]]; then
  echo "docs-guard: no changed files vs ${BASE_REF}"
  exit 0
fi

hits=()
for path in "${CHANGED[@]}"; do
  for prefix in "${PROTECTED[@]}"; do
    if [[ "$path" == "$prefix"* ]] || [[ "$path" == "$prefix" ]]; then
      hits+=("$path")
      break
    fi
  done
done

if [[ ${#hits[@]} -eq 0 ]]; then
  echo "docs-guard: protected docs untouched"
  exit 0
fi

TIP_MSG="$(git log -1 --pretty=%B)"
if grep -Fq '[docs-guard-bypass]' <<<"$TIP_MSG"; then
  echo "docs-guard: bypass trailer present; allowing protected-doc edits:"
  printf '  - %s\n' "${hits[@]}"
  exit 0
fi

echo "docs-guard: blocked protected documentation edits without [docs-guard-bypass]:"
printf '  - %s\n' "${hits[@]}"
echo
echo "These files are intentionally locked (expression rule cookbook / rule narrative)."
echo "If the change is intentional, amend the tip commit message with [docs-guard-bypass]."
exit 1
