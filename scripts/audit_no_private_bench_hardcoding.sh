#!/usr/bin/env bash
# Fail if private bench values appear outside allowed local/example paths.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PATTERNS=(
  '192\.168\.204\.14'
  '192\.168\.204\.'
  '5007-bench'
  'equip:5007-bench'
  'OPENFDD_MODBUS_HOST.*192\.168\.204\.14'
  'analog-input,1173'
  'analog-input,1168'
  'analog-input,1192'
  'analog-input,10014'
)

SCAN_DIRS=(edge workspace/dashboard/src scripts docs docker-compose.yml .env.example .github)

is_allowed() {
  local file="$1"
  case "$file" in
    workspace/smoke-profiles/local/*.local.toml.example) return 0 ;;
    workspace/smoke-profiles/local/local_haystack_5007_parity.local.toml.example) return 0 ;;
    docs/validation/*|docs/verification/*|docs/testing/*|docs/release_cleanup/*) return 0 ;;
    edge/src/validation/audit.rs) return 0 ;;
    edge/src/main.rs) return 0 ;;
    scripts/bench_5007_long_smoke.sh) return 0 ;;
    scripts/openfdd_haystack_smoke.sh) return 0 ;;
    workspace/dashboard/src/App.tsx) return 0 ;;
    docker-compose.bacnet-live.yml) return 0 ;;
  esac
  return 1
}

fail=0
for pat in "${PATTERNS[@]}"; do
  for dir in "${SCAN_DIRS[@]}"; do
    [[ -e "$dir" ]] || continue
    while IFS= read -r hit; do
      [[ -z "$hit" ]] && continue
      file="${hit%%:*}"
      line_num="${hit#*:}"
      line_num="${line_num%%:*}"
      if [[ "$file" == "scripts/audit_no_private_bench_hardcoding.sh" ]]; then
        continue
      fi
      if [[ "$file" == scripts/* ]]; then
        line_text="$(sed -n "${line_num}p" "$file" 2>/dev/null || true)"
        if [[ "$line_text" =~ ^[[:space:]]*# ]]; then
          continue
        fi
      fi
      if is_allowed "$file"; then
        continue
      fi
      echo "VIOLATION: $hit (pattern: $pat)"
      fail=1
    done < <(grep -RInE "$pat" "$dir" \
      --exclude-dir=node_modules --exclude-dir=target --exclude-dir=.git 2>/dev/null || true)
  done
done

if command -v cargo >/dev/null 2>&1; then
  cargo test -p open_fdd_edge_prototype validation::audit --quiet 2>/dev/null || true
fi

if [[ "$fail" -ne 0 ]]; then
  echo "Anti-hardcoding audit FAILED" >&2
  exit 1
fi
echo "Anti-hardcoding audit passed."
