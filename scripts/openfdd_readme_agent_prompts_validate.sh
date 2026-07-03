#!/usr/bin/env bash
# Validate README agent prompts (fetched live from GitHub) + local agent-prompts/ — no git clone.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_bench_lib.sh
source "$ROOT/scripts/openfdd_bench_lib.sh"
# shellcheck source=scripts/openfdd_gh_scope_lib.sh
source "$ROOT/scripts/openfdd_gh_scope_lib.sh"

openfdd_bench_load_profile "$ROOT" || true

RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_DIR="${OPENFDD_PROMPTS_DIR:-$ROOT/workspace/logs/agent_prompts_${RUN_TS}}"
README_URL="${OPENFDD_README_RAW_URL:-https://raw.githubusercontent.com/bbartling/open-fdd/refs/heads/master/README.md}"
MCP_README_URL="${OPENFDD_MCP_README_RAW_URL:-https://raw.githubusercontent.com/bbartling/open-fdd/refs/heads/master/mcp/README.md}"

mkdir -p "$LOG_DIR/agent-prompts-fetched"
exec > >(tee -a "$LOG_DIR/prompts.log") 2>&1

pass=0 fail=0 skip=0 FAIL=0
check() {
  openfdd_bench_check_line "$1" "$2" "$3" "$LOG_DIR/summary.txt"
  case "$2" in pass) pass=$((pass + 1)) ;; skip) skip=$((skip + 1)) ;; *) fail=$((fail + 1)); FAIL=1 ;; esac
}

: >"$LOG_DIR/summary.txt"
log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

log "=== README + agent prompt validation ==="

openfdd_gh_fetch_raw "$README_URL" "$LOG_DIR/README.master.md" \
  && check "fetch-readme" pass "$README_URL" \
  || check "fetch-readme" fail "README fetch failed"

openfdd_gh_fetch_raw "$MCP_README_URL" "$LOG_DIR/mcp.README.master.md" \
  && check "fetch-mcp-readme" pass "$MCP_README_URL" \
  || check "fetch-mcp-readme" skip "mcp/README.md not yet on master"

# README MCP sidecar section markers (3.2.3+)
for marker in \
  "ghcr.io/bbartling/openfdd-mcp" \
  "OPENFDD_MCP_TOKEN" \
  "stdio JSON-RPC" \
  "openfdd_rust_edge_bootstrap.sh"; do
  if grep -qF "$marker" "$LOG_DIR/README.master.md" 2>/dev/null; then
    check "readme-mcp-marker" pass "$marker"
  else
    check "readme-mcp-marker" fail "README missing MCP/bootstrap marker: $marker"
  fi
done

# Required OpenClaw prompt markers in README (agent turn-key)
for marker in \
  "Never run docker compose down -v" \
  "bootstrap_credentials.once.txt" \
  "openfdd_rust_site_update.sh" \
  "GET /api/health"; do
  if grep -qF "$marker" "$LOG_DIR/README.master.md" 2>/dev/null; then
    check "readme-marker" pass "$marker"
  else
    check "readme-marker" fail "README missing: $marker"
  fi
done

# Extract OpenClaw prompt blocks to files for future agents
prompt_count="$(python3 - "$LOG_DIR/README.master.md" "$LOG_DIR/agent-prompts-fetched" <<'PY'
import re, sys, pathlib
text = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
out = pathlib.Path(sys.argv[2])
blocks = re.findall(r"```text\n(.*?)```", text, re.DOTALL)
for i, b in enumerate(blocks, 1):
    if "OpenClaw" in b or "Open-FDD" in b:
        (out / f"readme_openclaw_{i}.txt").write_text(b.strip() + "\n")
print(len(blocks))
PY
)"
echo "$prompt_count" >"$LOG_DIR/extracted_prompt_count.txt"

prompt_count="$(cat "$LOG_DIR/extracted_prompt_count.txt" 2>/dev/null || echo 0)"
if [[ "${prompt_count:-0}" -ge 3 ]]; then
  check "readme-openclaw-blocks" pass "extracted $prompt_count OpenClaw prompt blocks"
else
  check "readme-openclaw-blocks" fail "expected ≥3 OpenClaw prompts in README"
fi

# Backup/restore lifecycle markers (OpenClaw update prompt + bench historian scripts)
for marker in \
  "openfdd_rust_site_backup.sh" \
  "openfdd_rust_site_update.sh" \
  "openfdd_rust_edge_validate.sh" \
  "openfdd_rust_historian_staging.sh" \
  "openfdd_post_update_data_recovery.sh"; do
  if grep -qF "$marker" "$LOG_DIR/README.master.md" 2>/dev/null; then
    check "readme-lifecycle-marker" pass "$marker in README"
  elif [[ -x "$ROOT/scripts/$marker" ]]; then
    check "readme-lifecycle-marker" pass "$marker on bench (README may lag upstream)"
  else
    check "readme-lifecycle-marker" fail "missing lifecycle: $marker"
  fi
done

# Local historian restore scripts (bench harness — may ship before upstream README)
for script in openfdd_rust_historian_staging.sh openfdd_rust_site_restore.sh openfdd_auth_rbac_validate.sh; do
  if [[ -x "$ROOT/scripts/$script" ]]; then
    check "bench-script-$script" pass "present and executable"
  else
    check "bench-script-$script" fail "missing $ROOT/scripts/$script"
  fi
done
REPORT="$ROOT/workspace/reports/BENCH_VALIDATION_REPORT.md"
if [[ -f "$REPORT" ]]; then
  cp "$REPORT" "$LOG_DIR/BENCH_VALIDATION_REPORT.md"
  grep -qi 'no git clone\|docker pull only' "$REPORT" \
    && check "bench-validation-report" pass "consolidated report + agent prompt present" \
    || check "bench-validation-report" fail "report must state no git clone on bench"
  grep -qE 'Cursor agent prompt|WSL Cursor builder agent prompt' "$REPORT" \
    && check "bench-builder-prompt" pass "fix prompt embedded in report" \
    || check "bench-builder-prompt" fail "report must embed Cursor agent prompt section"
else
  check "bench-validation-report" fail "missing $REPORT"
fi

# MCP tool contract doc (if fetched)
if [[ -f "$LOG_DIR/mcp.README.master.md" ]]; then
  grep -q 'stdio' "$LOG_DIR/mcp.README.master.md" \
    && check "mcp-readme-stdio" pass "MCP README documents stdio transport" \
    || check "mcp-readme-stdio" fail "MCP README must document stdio JSON-RPC"
fi

jq -nc --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg dir "$LOG_DIR" \
  --argjson pass "$pass" --argjson fail "$fail" --argjson skip "$skip" \
  '{timestamp_utc:$ts,artifact_dir:$dir,pass_count:$pass,fail_count:$fail,skip_count:$skip,ok:($fail==0)}' \
  >"$LOG_DIR/result.json"

[[ "$FAIL" -eq 0 ]]
