#!/usr/bin/env bash
# Product-default docs must not point users at host :3000 (static UI is :8080/app/).
# React rollback docs may still mention :3000 — see allowlist below.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

PRODUCT_DEFAULT_DOCS=(
  docs/quick-start/local-stack.md
  docs/quick-start/docker-ghcr.md
  docs/operations/VM_DEPLOYMENT.md
  docs/frontend/STATIC_SERVE_STRATEGY.md
  docs/migration/react-rust/NO_PYTHON_STACK.md
  docs/operations/LOCAL_DEPLOYMENT.md
  docs/architecture/services.md
)

allow_file() {
  local f="$1"
  case "$f" in
    docs/operations/LOCAL_HOSTING.md|docs/operations/build-recipes.md|docs/operations/security.md|docs/archive/*|docs/agent/linux-edge-tester-*|docs/operations/BUG_REPORT_*|docs/operations/patch_trains/*|archive/*|openfdd_agent_spec/*|.agents/*|.claude/*|.cursor/*|AGENTS.md|mcp/README.md|mcp/INSTRUCTIONS.md)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

hits=0
for f in "${PRODUCT_DEFAULT_DOCS[@]}"; do
  if [[ ! -f "$f" ]]; then
    echo "FAIL: missing guard doc $f" >&2
    hits=1
    continue
  fi
  if rg -n ':3000' "$f" >/dev/null 2>&1; then
    echo "FAIL: :3000 in product-default doc $f:" >&2
    rg -n ':3000' "$f" >&2 || true
    hits=1
  fi
done

while IFS= read -r line; do
  file="${line%%:*}"
  if allow_file "$file"; then
    continue
  fi
  case "$file" in
    docs/agent/*|docs/migration/*|docs/frontend/*)
      echo "WARN: :3000 outside rollback allowlist (review): $line" >&2
      ;;
  esac
done < <(rg -n ':3000' docs 2>/dev/null | rg -v 'rollback|React rollback|openfdd-web' || true)

if [[ "$hits" -ne 0 ]]; then
  exit 1
fi
echo "OK forbid_port_3000_product_docs.sh"
