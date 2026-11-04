#!/usr/bin/env bash
# Fail when maintainer machine paths appear in operator-facing public docs.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

fail=0

allow_path() {
  local path="$1"
  case "$path" in
    docs/archive/*|docs/agent/*|docs/operations/patch_trains/*|docs/operations/BUG_REPORT_*|docs/operations/BENCH_*|docs/migration/vibe21/*|docs/superpowers/*)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

while IFS= read -r file; do
  [[ -n "$file" ]] || continue
  if allow_path "$file"; then
    continue
  fi
  if grep -qE '/home/[^/[:space:]]+|/Users/[^/[:space:]]+' "$file"; then
    echo "FAIL: machine-specific path in public doc: $file" >&2
    grep -nE '/home/[^/[:space:]]+|/Users/[^/[:space:]]+' "$file" | head -5 >&2 || true
    fail=1
  fi
done < <(git ls-files docs/quick-start docs/architecture docs/frontend docs/operations | grep -E '\.md$' || true)

if [[ "$fail" -ne 0 ]]; then
  echo "forbid_machine_paths_public_docs: FAIL" >&2
  exit 1
fi

echo "PASS forbid_machine_paths_public_docs.sh"
