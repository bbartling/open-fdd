#!/usr/bin/env bash
# Scan production paths for bench-specific hardcoding.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PATTERNS=(
  'bench_5007'
  'bench-5007'
  'BENCH_5007'
  'Bench 5007'
  '/api/bench/5007'
  '/bench-5007'
)

ALLOWED=(
  'scripts/'
  'docs/testing/'
  'docs/verification/'
  'workspace/smoke-profiles/'
  'edge/src/validation/audit.rs'
  'edge/src/main.rs'
  'docker-compose.bacnet-live.yml'
  'scripts/bench_5007_long_smoke.sh'
  'workspace/dashboard/src/App.tsx'
)

fail=0
for pat in "${PATTERNS[@]}"; do
  for dir in "${SCAN_DIRS[@]}"; do
    [[ -d "$dir" ]] || continue
    while IFS= read -r hit; do
      [[ -z "$hit" ]] && continue
      file="${hit%%:*}"
      allowed=false
      for prefix in "${ALLOWED[@]}"; do
        if [[ "$file" == *"$prefix"* ]] || [[ "$file" == "$prefix" ]]; then
          allowed=true
          break
        fi
      done
      if [[ "$allowed" == false ]]; then
        echo "VIOLATION: $hit (pattern: $pat)"
        fail=1
      fi
    done < <(grep -RIn "$pat" "$dir" \
      --exclude-dir=node_modules --exclude-dir=target 2>/dev/null || true)
  done
done

if command -v cargo >/dev/null 2>&1; then
  cargo test -p open_fdd_edge_prototype validation::audit --quiet
else
  echo "WARN: cargo not installed locally; skipping Rust audit unit tests (CI will run them)"
fi

if [[ "$fail" -ne 0 ]]; then
  echo "No-hardcoding audit FAILED" >&2
  exit 1
fi
echo "No-hardcoding audit passed."
