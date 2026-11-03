#!/usr/bin/env bash
# Fail when :3000 is documented as the default product UI outside archive / rollback paths.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

fail=0

allow_path() {
  local path="$1"
  case "$path" in
    archive/*|docker/compose.react.yml|docker/compose.caddy.react.yml|docker/caddy/Caddyfile.react.http)
      return 0
      ;;
    docs/operations/LOCAL_HOSTING.md|docs/operations/build-recipes.md|docs/frontend/STATIC_SERVE_STRATEGY.md|docs/architecture/services.md)
      return 0
      ;;
    docs/operations/GROK_CLOUD_STATIC_UI_HANDOFF.md|docs/maintenance/*|docs/archive/*|docs/agent/*|docs/operations/BUG_REPORT_*|docs/operations/LOCAL_BACNET_*)
      return 0
      ;;
    scripts/release/smoke_csv_central_boot.sh|scripts/ci/static_product_guard.sh)
      return 0
      ;;
    openfdd_agent_spec/CONTAINER_AGENT.md|openfdd_agent_spec/AGENTS.md|AGENTS.md)
      return 0
      ;;
    .agents/skills/*|.claude/skills/*|.cursor/skills/*|openfdd_agent_spec/skills/*)
      return 0
      ;;
    mcp/*|tests/security/test_standalone_https_compose.py|tests/qualification/*|tests/selenium/*)
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
  if grep -qE '127\.0\.0\.1:3000|:3000/app|UI.*:3000|http://[^ ]*:3000' "$file"; then
    echo "FAIL: default UI :3000 reference in non-rollback doc: $file" >&2
    fail=1
  fi
done < <(git ls-files | grep -E '\.(md|yml|yaml)$' || true)

if [[ "$fail" -ne 0 ]]; then
  echo "forbid_product_ui_port_3000_docs: FAIL" >&2
  exit 1
fi

echo "PASS forbid_product_ui_port_3000_docs.sh"
