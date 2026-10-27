#!/usr/bin/env bash
# Fail if private bench values appear outside allowed local/example paths.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PATTERNS=(
  '192\.168\.204\.14'
  '192\.168\.204\.'
  '5007-bench'
  'equip:5007'
  'equip:5007-bench'
  'BENS BENCHTEST BOX'
  'ACTUATOR-0'
  'C06-0-10VDC-O'
  'ACTUATOR-POS'
  'STAT ZN-T'
  'DUCT-T'
  'OA-T'
  'OA-H'
  'analogInput:1168'
  'analogInput:1173'
  'analogInput:1192'
  'analogInput:10014'
  'analog-input,1168'
  'analog-input,1173'
  'analog-input,1192'
  'analog-input,10014'
  'OPENFDD_MODBUS_HOST.*192\.168\.204\.14'
)

SCAN_DIRS=(edge workspace/dashboard/src scripts docs docker .env.example .github)

is_allowed() {
  local file="$1"
  case "$file" in
    workspace/smoke-profiles/local/*.local.toml.example) return 0 ;;
    workspace/smoke-profiles/local/local_5007_validation.local.toml.example) return 0 ;;
    workspace/smoke-profiles/local/local_haystack_5007_parity.local.toml.example) return 0 ;;
    tests/fixtures/*) return 0 ;;
    edge/tests/fixtures/*) return 0 ;;
    docs/validation/*|docs/verification/*|docs/testing/*|docs/release_cleanup/*) return 0 ;;
    docs/agent/bench-driver-setup-wsl-agent.md) return 0 ;;
    docs/agent/bench-*-closeout-agent-prompt.md) return 0 ;;
    docs/agent/linux-edge-tester-*.md) return 0 ;;
    docs/agent/vibe19-parity-nightly-monster-prompt.md) return 0 ;;
    docs/archive/*) return 0 ;;
    docs/archive/agent/bench-driver-setup-wsl-agent.md) return 0 ;;
    docs/archive/verification/bacnet-nic-setup.md) return 0 ;;
    docs/archive/release_cleanup/current_pr_issue_ledger.md) return 0 ;;
    edge/src/validation/audit.rs) return 0 ;;
    edge/src/main.rs) return 0 ;;
    # Lab portal smoke names the on-site points. Product selectors must not.
    scripts/nf/*) return 0 ;;
    # BACpypes3 diagnose-only doc (archived OT lane) — private bench bind examples OK here.
    docs/operations/LOCAL_BACNET_BACPYPE3_BENCH.md) return 0 ;;
    scripts/audit_no_private_bench_hardcoding.sh) return 0 ;;
    # NF portal client uses the portal's own point names (Wave-A). Not bench IPs.
    scripts/nf/*) return 0 ;;
    docker/compose.react.fieldbus.local.example.yml) return 0 ;;
    docker/compose.standalone.local.yml) return 0 ;;
    workspace/dashboard/src/App.tsx) return 0 ;;
  esac
  return 1
}

fail=0
hits=0
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
      if [[ "$file" == edge/workspace/* ]]; then
        continue
      fi
      if is_allowed "$file"; then
        echo "ALLOWED: $hit (pattern: $pat)"
        continue
      fi
      echo "VIOLATION: $hit (pattern: $pat)"
      fail=1
      hits=$((hits + 1))
    done < <(grep -RInE "$pat" "$dir" \
      --exclude-dir=node_modules --exclude-dir=target --exclude-dir=.git 2>/dev/null || true)
  done
done

if command -v cargo >/dev/null 2>&1; then
  cargo test -p open_fdd_edge_prototype validation::audit --quiet 2>/dev/null || true
fi

# Tracked NF site configs must be the shipped example only (T1401-7).
while IFS= read -r nf_site; do
  [[ -z "$nf_site" ]] && continue
  base="$(basename "$nf_site")"
  if [[ "$base" != "provider_sites.example.json" ]]; then
    echo "VIOLATION: tracked $nf_site — real site configs belong outside git (see scripts/nf/.gitignore)" >&2
    fail=1
    hits=$((hits + 1))
  fi
done < <(git ls-files 'scripts/nf/provider_sites*.json' 2>/dev/null || true)

EXAMPLE_SITES="scripts/nf/provider_sites.example.json"
if git ls-files --error-unmatch "$EXAMPLE_SITES" >/dev/null 2>&1; then
  if grep -qE 'normal-online\.net' "$EXAMPLE_SITES"; then
    echo "VIOLATION: $EXAMPLE_SITES must not contain normal-online.net URLs" >&2
    fail=1
    hits=$((hits + 1))
  fi
  if grep -qE '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' "$EXAMPLE_SITES"; then
    echo "VIOLATION: $EXAMPLE_SITES must not contain real NF point UUIDs" >&2
    fail=1
    hits=$((hits + 1))
  fi
  while IFS= read -r line; do
    if [[ "$line" == *\"client_secret\"* ]] && [[ "$line" != *env:* ]]; then
      echo "VIOLATION: $EXAMPLE_SITES client_secret must use env: refs" >&2
      fail=1
      hits=$((hits + 1))
      break
    fi
  done < "$EXAMPLE_SITES"
fi

for forbidden in \
  scripts/nf/provider_sites.acme.json \
  scripts/nf/provider_sites.bosspi.json \
  scripts/nf/bosspi_gateway.json \
  scripts/nf/bosspi_semantic_meta.json \
  scripts/nf/check_acme_portal_fresh.py; do
  if git ls-files --error-unmatch "$forbidden" >/dev/null 2>&1; then
    echo "VIOLATION: site-named file still tracked: $forbidden" >&2
    fail=1
    hits=$((hits + 1))
  fi
done

if [[ ! -f scripts/nf/check_portal_fresh.py ]]; then
  echo "VIOLATION: missing scripts/nf/check_portal_fresh.py" >&2
  fail=1
  hits=$((hits + 1))
fi

if [[ "$fail" -ne 0 ]]; then
  echo "Anti-hardcoding audit FAILED ($hits violation(s))" >&2
  exit 1
fi
echo "Anti-hardcoding audit passed."
