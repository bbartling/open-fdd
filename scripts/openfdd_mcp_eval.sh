#!/usr/bin/env bash
# Evaluate ghcr.io/bbartling/openfdd-mcp sidecar (stdio JSON-RPC) — NOT in edge image.
# Matches README: https://github.com/bbartling/open-fdd#optional-mcp-sidecar-after-edge-update
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_bench_lib.sh
source "$ROOT/scripts/openfdd_bench_lib.sh"
# shellcheck source=scripts/openfdd_auth_lib.sh
source "$ROOT/scripts/openfdd_auth_lib.sh"
# shellcheck source=scripts/openfdd_gh_scope_lib.sh
source "$ROOT/scripts/openfdd_gh_scope_lib.sh"

openfdd_bench_load_profile "$ROOT" || true

TAG="${OPENFDD_MCP_GHCR_TAG:-${OPENFDD_GHCR_TAG:-${OPENFDD_EXPECT_VERSION:-latest}}}"
MCP_IMAGE="${OPENFDD_MCP_GHCR_IMAGE:-ghcr.io/bbartling/openfdd-mcp}:${TAG}"
BRIDGE="${OPENFDD_API_BASE:-http://127.0.0.1:8080}"
COMMISSION="${OPENFDD_COMMISSION_BASE:-http://127.0.0.1:9091}"
AUTH="${OPENFDD_AUTH_ENV:-$ROOT/workspace/auth.env.local}"
EXPECT_TOOLS="${OPENFDD_MCP_EXPECT_TOOLS:-[]}"

RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_DIR="${OPENFDD_MCP_EVAL_DIR:-$ROOT/workspace/logs/mcp_eval_${RUN_TS}}"

mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_DIR/mcp_eval.log") 2>&1

pass=0 fail=0 skip=0 FAIL=0
log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }
check() {
  openfdd_bench_check_line "$1" "$2" "$3" "$LOG_DIR/summary.txt"
  case "$2" in pass) pass=$((pass + 1)) ;; skip) skip=$((skip + 1)) ;; *) fail=$((fail + 1)); FAIL=1 ;; esac
}

: >"$LOG_DIR/summary.txt"
log "=== MCP sidecar evaluation → $LOG_DIR ==="
log "image=$MCP_IMAGE (separate from edge-rust)"

# MCP must NOT be in bridge (3.2.3+ architecture)
bridge_cid="$(docker ps -qf 'name=openfdd-bridge' 2>/dev/null | head -1 || true)"
if [[ -n "$bridge_cid" ]]; then
  if docker exec "$bridge_cid" sh -c 'command -v openfdd-mcp' >/dev/null 2>&1; then
    check "mcp-not-in-bridge" fail "openfdd-mcp found in bridge — should be sidecar only"
  else
    check "mcp-not-in-bridge" pass "MCP correctly absent from bridge container"
  fi
fi

# Pull sidecar image
if [[ "${OPENFDD_SKIP_PULL:-0}" != "1" ]]; then
  log "docker pull $MCP_IMAGE"
  docker pull "$MCP_IMAGE" 2>"$LOG_DIR/docker_pull.err" || log "WARN: MCP pull failed"
fi

if docker image inspect "$MCP_IMAGE" >/dev/null 2>&1; then
  check "mcp-image" pass "local image $MCP_IMAGE"
else
  check "mcp-image" fail "MCP image not available — wait for GH Actions GHCR publish"
fi

# Fetch live MCP README tool contract (no clone)
MCP_README_URL="${OPENFDD_MCP_README_RAW_URL:-https://raw.githubusercontent.com/bbartling/open-fdd/refs/heads/master/mcp/README.md}"
if openfdd_gh_fetch_raw "$MCP_README_URL" "$LOG_DIR/mcp.README.master.md"; then
  check "mcp-readme" pass "fetched mcp/README.md from GitHub"
  grep -q 'stdio' "$LOG_DIR/mcp.README.master.md" && check "mcp-stdio-doc" pass "README documents stdio" \
    || check "mcp-stdio-doc" fail "README must document stdio JSON-RPC"
else
  check "mcp-readme" skip "mcp/README.md not on master yet"
fi

# JWT for MCP (agent workflow from README)
MCP_TOKEN=""
if MCP_TOKEN="$(openfdd_auth_login_token "$BRIDGE" "$AUTH" integrator 2>/dev/null)" && [[ -n "$MCP_TOKEN" ]]; then
  check "mcp-jwt" pass "integrator JWT for OPENFDD_MCP_TOKEN"
else
  check "mcp-jwt" fail "cannot obtain JWT — agent bootstrap must fix auth first"
fi

MCP_STDIO_OK=false
if [[ -n "$MCP_TOKEN" ]] && docker image inspect "$MCP_IMAGE" >/dev/null 2>&1; then
  init_req='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"openfdd-bench","version":"1.0"}}}'
  tools_req='{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
  notified='{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}'
  {
    echo "$init_req"
    sleep 0.2
    echo "$notified"
    sleep 0.2
    echo "$tools_req"
  } | timeout 25 docker run --rm -i --network host \
    -e "OPENFDD_API_BASE=$BRIDGE" \
    -e "OPENFDD_COMMISSION_BASE=$COMMISSION" \
    -e "OPENFDD_MCP_TOKEN=$MCP_TOKEN" \
    "$MCP_IMAGE" 2>"$LOG_DIR/mcp_stdio.err" | tee "$LOG_DIR/mcp_stdio.ndjson" || true

  if grep -q '"tools"' "$LOG_DIR/mcp_stdio.ndjson" 2>/dev/null; then
    MCP_STDIO_OK=true
    jq -s '[.[] | select(.result.tools != null) | .result.tools[]?.name] | unique' \
      "$LOG_DIR/mcp_stdio.ndjson" >"$LOG_DIR/tools_found.json" 2>/dev/null || echo '[]' >"$LOG_DIR/tools_found.json"
    check "stdio-tools-list" pass "tools/list on MCP sidecar stdio"
  else
    check "stdio-tools-list" fail "no tools/list — see mcp_stdio.err"
    echo '[]' >"$LOG_DIR/tools_found.json"
  fi
else
  check "stdio-tools-list" skip "missing image or token"
  echo '[]' >"$LOG_DIR/tools_found.json"
fi

# Tool diff vs bench profile (agent-updatable list)
tools_found="$(cat "$LOG_DIR/tools_found.json" 2>/dev/null || echo '[]')"
python3 - "$LOG_DIR" "$EXPECT_TOOLS" "$tools_found" <<'PY'
import json, sys, pathlib
log_dir = pathlib.Path(sys.argv[1])
expect = json.loads(sys.argv[2]) if sys.argv[2] else []
found = json.loads(sys.argv[3])
missing = sorted(set(expect) - set(found)) if found else []
extra = sorted(set(found) - set(expect)) if found else []
report = {"expected_tools": expect, "found_tools": found, "missing_tools": missing, "extra_tools": extra,
          "layout_ok": (len(missing) == 0) if found else None}
(log_dir / "tool_diff.json").write_text(json.dumps(report, indent=2))
PY

found_count="$(jq '.found_tools | length' "$LOG_DIR/tool_diff.json" 2>/dev/null || echo 0)"
if [[ "$found_count" -gt 0 ]]; then
  missing="$(jq '.missing_tools | length' "$LOG_DIR/tool_diff.json")"
  [[ "$missing" -eq 0 ]] && check "tool-surface" pass "$found_count tools match profile" \
    || check "tool-surface" fail "$(jq -r '.missing_tools | join(", ")' "$LOG_DIR/tool_diff.json") missing"
else
  check "tool-surface" skip "MCP sidecar did not respond — wait for GHCR publish"
fi

# openfdd_health tools/call smoke (3.2.3 tool name)
if [[ "$MCP_STDIO_OK" == true ]] && jq -e '.found_tools | index("openfdd_health")' "$LOG_DIR/tool_diff.json" >/dev/null 2>&1; then
  call='{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"openfdd_health","arguments":{}}}'
  {
    echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"bench","version":"1"}}}'
    sleep 0.2
    echo '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}'
    sleep 0.2
    echo "$call"
  } | timeout 25 docker run --rm -i --network host \
    -e "OPENFDD_API_BASE=$BRIDGE" -e "OPENFDD_COMMISSION_BASE=$COMMISSION" -e "OPENFDD_MCP_TOKEN=$MCP_TOKEN" \
    "$MCP_IMAGE" 2>/dev/null | tee "$LOG_DIR/mcp_openfdd_health.ndjson" || true
  grep -q '"content"' "$LOG_DIR/mcp_openfdd_health.ndjson" 2>/dev/null \
    && jq -e '.result.content[0].text | test("ok|3\\.2\\.3|health")' "$LOG_DIR/mcp_openfdd_health.ndjson" >/dev/null 2>&1 \
    && check "ai-openfdd_health" pass "tools/call openfdd_health returns live data" \
    || check "ai-openfdd_health" fail "openfdd_health call missing expected health payload"
else
  check "ai-openfdd_health" skip "openfdd_health unavailable"
fi

# Driver status bundle — validates MCP proxies bridge REST with real driver data
if [[ "$MCP_STDIO_OK" == true ]] && jq -e '.found_tools | index("openfdd_driver_status")' "$LOG_DIR/tool_diff.json" >/dev/null 2>&1; then
  call='{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"openfdd_driver_status","arguments":{}}}'
  {
    echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"bench","version":"1"}}}'
    sleep 0.2
    echo '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}'
    sleep 0.2
    echo "$call"
  } | timeout 25 docker run --rm -i --network host \
    -e "OPENFDD_API_BASE=$BRIDGE" -e "OPENFDD_COMMISSION_BASE=$COMMISSION" -e "OPENFDD_MCP_TOKEN=$MCP_TOKEN" \
    "$MCP_IMAGE" 2>/dev/null | tee "$LOG_DIR/mcp_openfdd_driver_status.ndjson" || true
  grep -q '"content"' "$LOG_DIR/mcp_openfdd_driver_status.ndjson" 2>/dev/null \
    && check "ai-openfdd_driver_status" pass "tools/call openfdd_driver_status OK" \
    || check "ai-openfdd_driver_status" fail "openfdd_driver_status call failed"
else
  check "ai-openfdd_driver_status" skip "openfdd_driver_status unavailable"
fi

# MCP README clarity for WSL agents (TLS bootstrap cross-ref)
MCP_README_URL="${OPENFDD_MCP_README_RAW_URL:-https://raw.githubusercontent.com/bbartling/open-fdd/refs/heads/master/mcp/README.md}"
if openfdd_gh_fetch_raw "$MCP_README_URL" "$LOG_DIR/mcp.README.clarity.md"; then
  grep -qi 'stdio' "$LOG_DIR/mcp.README.clarity.md" && check "mcp-doc-stdio" pass "README documents stdio transport" \
    || check "mcp-doc-stdio" fail "README must document stdio JSON-RPC"
  grep -q 'OPENFDD_MCP_TOKEN' "$LOG_DIR/mcp.README.clarity.md" && check "mcp-doc-jwt" pass "README documents OPENFDD_MCP_TOKEN" \
    || check "mcp-doc-jwt" fail "README must document JWT env for agents"
  if grep -Eqi 'caddy-tls|self-signed|tls generate|OPENFDD_CADDY' "$LOG_DIR/mcp.README.clarity.md"; then
    check "mcp-doc-tls-bootstrap" pass "README mentions TLS/self-signed ingress"
  else
    check "mcp-doc-tls-bootstrap" fail "README missing TLS bootstrap — agents need openfdd_caddy_test_recipe.sh caddy-tls + haystack tls_verify=false"
  fi
else
  check "mcp-doc-clarity" skip "could not fetch MCP README for clarity eval"
fi

jq -nc --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg dir "$LOG_DIR" \
  --argjson pass "$pass" --argjson fail "$fail" --argjson skip "$skip" \
  --slurpfile diff "$LOG_DIR/tool_diff.json" \
  '{timestamp_utc:$ts,artifact_dir:$dir,pass_count:$pass,fail_count:$fail,skip_count:$skip,tool_diff:$diff[0],ok:($fail==0)}' \
  >"$LOG_DIR/result.json"

[[ "$FAIL" -eq 0 ]]
