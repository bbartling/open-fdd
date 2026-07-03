#!/usr/bin/env bash
# AI-agent turn-key bootstrap validation — .env / secrets / haystack wiring (no git clone).
# Simulates what a future AI agent must do before driver tests run.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_bench_lib.sh
source "$ROOT/scripts/openfdd_bench_lib.sh"
# shellcheck source=scripts/openfdd_auth_lib.sh
source "$ROOT/scripts/openfdd_auth_lib.sh"
# shellcheck source=scripts/openfdd_gh_scope_lib.sh
source "$ROOT/scripts/openfdd_gh_scope_lib.sh"

openfdd_bench_load_profile "$ROOT" || true

RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_DIR="${OPENFDD_BOOTSTRAP_DIR:-$ROOT/workspace/logs/bootstrap_validate_${RUN_TS}}"
BRIDGE="${OPENFDD_API_BASE:-http://127.0.0.1:8080}"
AUTH="${OPENFDD_AUTH_ENV:-$ROOT/workspace/auth.env.local}"

mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_DIR/bootstrap.log") 2>&1

pass=0 fail=0 FAIL=0
check() {
  openfdd_bench_check_line "$1" "$2" "$3" "$LOG_DIR/summary.txt"
    if [[ "$2" == pass ]]; then pass=$((pass + 1));
    elif [[ "$2" == skip ]]; then :;
    else fail=$((fail + 1)); FAIL=1; fi
}

: >"$LOG_DIR/summary.txt"
log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

log "=== AI bootstrap / .env validation ==="

# --- Required paths (agent must ensure exist — not git clone) ---
for f in \
  "$ROOT/docker-compose.yml" \
  "$ROOT/workspace/auth.env.local" \
  "$ROOT/workspace/bench/bench_profile.toml" \
  "$ROOT/workspace/bacnet/commissioning/commission.env"; do
  if [[ -f "$f" ]]; then
    check "path-$(basename "$f")" pass "exists"
  else
    check "path-$(basename "$f")" fail "missing — agent must create/configure"
  fi
done

# --- .env.example pattern (agent copies to .env / data.env.local) ---
if [[ -f "$ROOT/.env.example" ]]; then
  check "env-example" pass ".env.example present for agent copy"
  cp "$ROOT/.env.example" "$LOG_DIR/env.example.reference"
else
  check "env-example" skip "no .env.example at site root (may use workspace/*.env.local only)"
fi

# data.env.local — haystack creds (agent sets OPENFDD_HAYSTACK_*)
DATA_ENV="$ROOT/workspace/data.env.local"
if [[ -f "$DATA_ENV" ]]; then
  grep -q 'OPENFDD_HAYSTACK' "$DATA_ENV" && check "data-env-haystack" pass "OPENFDD_HAYSTACK_* in data.env.local" \
    || check "data-env-haystack" fail "agent must set OPENFDD_HAYSTACK_* in data.env.local"
  grep -q '^OPENFDD_HAYSTACK_USER=' "$DATA_ENV" && check "data-env-haystack-user" pass "OPENFDD_HAYSTACK_USER set" \
    || check "data-env-haystack-user" fail "missing OPENFDD_HAYSTACK_USER (use open_fdd)"
  if grep -q '^OPENFDD_HAYSTACK_PASS=.' "$DATA_ENV" 2>/dev/null; then
    check "data-env-haystack-pass" pass "OPENFDD_HAYSTACK_PASS set (not logged)"
  else
    check "data-env-haystack-pass" fail "missing OPENFDD_HAYSTACK_PASS — set from Niagara, restart stack"
  fi
else
  check "data-env-haystack" fail "workspace/data.env.local missing — agent must create from README"
fi

# commission.env — local BACnet server must stay enabled (599999)
COMM_ENV="$ROOT/workspace/bacnet/commissioning/commission.env"
if [[ -f "$COMM_ENV" ]]; then
  if grep -qE '^OPENFDD_BACNET_SERVER_ENABLED=(1|true|yes)$' "$COMM_ENV" \
    || ! grep -q '^OPENFDD_BACNET_SERVER_ENABLED=' "$COMM_ENV"; then
    check "commission-bacnet-server" pass "OPENFDD_BACNET_SERVER_ENABLED=1 (default on)"
  else
    check "commission-bacnet-server" fail "agent must set OPENFDD_BACNET_SERVER_ENABLED=1 — never disable on deploy"
  fi
  if [[ -f "$DATA_ENV" ]] && grep -qE '^OPENFDD_BACNET_SERVER_ENABLED=(0|false|no)$' "$DATA_ENV"; then
    check "data-env-bacnet-server" fail "remove OPENFDD_BACNET_SERVER_ENABLED=0 from data.env.local"
  elif [[ -f "$DATA_ENV" ]] && grep -qE '^OPENFDD_BACNET_SERVER_ENABLED=' "$DATA_ENV"; then
    check "data-env-bacnet-server" pass "data.env.local keeps BACnet server enabled"
  fi
fi

# haystack toml — agent configures from README
HS_TOML="$ROOT/workspace/haystack/local.nhaystack.toml"
if [[ -f "$HS_TOML" ]]; then
  cp "$HS_TOML" "$LOG_DIR/local.nhaystack.toml.snapshot"
  grep -q 'auth_mode.*basic' "$HS_TOML" && check "haystack-auth-mode" pass "auth_mode=basic" \
    || check "haystack-auth-mode" fail "agent must set auth_mode=basic for Niagara"
  grep -q 'tls_verify.*false' "$HS_TOML" && check "haystack-tls" pass "tls_verify=false" \
    || check "haystack-tls" fail "agent must set tls_verify=false for self-signed"
else
  check "haystack-toml" fail "workspace/haystack/local.nhaystack.toml missing"
fi

# bootstrap credentials handoff
HANDOFF="$ROOT/workspace/bootstrap_credentials.once.txt"
if [[ -f "$HANDOFF" ]]; then
  check "bootstrap-handoff" pass "bootstrap_credentials.once.txt present"
else
  check "bootstrap-handoff" skip "no handoff file (auth.env.local may still work)"
fi

# Login smoke — agent workflow
if TOKEN="$(openfdd_auth_login_token "$BRIDGE" "$AUTH" integrator 2>/dev/null)" && [[ -n "$TOKEN" ]]; then
  check "agent-login" pass "integrator JWT from auth.env.local + handoff"
  echo "$TOKEN" | wc -c >"$LOG_DIR/token_len.txt"
else
  check "agent-login" fail "integrator login failed — agent must fix auth.env.local / handoff"
fi

# Fetch README bootstrap section (read-only) for agent prompt drift check
README_URL="${OPENFDD_README_RAW_URL:-https://raw.githubusercontent.com/bbartling/open-fdd/refs/heads/master/README.md}"
if openfdd_gh_fetch_raw "$README_URL" "$LOG_DIR/README.master.md"; then
  check "readme-fetch" pass "README fetched from GitHub raw (no clone)"
  grep -q 'openfdd_rust_edge_bootstrap.sh' "$LOG_DIR/README.master.md" \
    && check "readme-bootstrap-script" pass "bootstrap script URL in README" \
    || check "readme-bootstrap-script" fail "README missing bootstrap script reference"
  grep -q 'openfdd-mcp' "$LOG_DIR/README.master.md" \
    && check "readme-mcp-sidecar" pass "MCP sidecar documented in README" \
    || check "readme-mcp-sidecar" fail "README missing MCP sidecar section"
else
  check "readme-fetch" fail "could not fetch README from $README_URL"
fi

jq -nc --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg dir "$LOG_DIR" \
  --argjson pass "$pass" --argjson fail "$fail" \
  '{timestamp_utc:$ts,artifact_dir:$dir,pass_count:$pass,fail_count:$fail,ok:($fail==0)}' \
  >"$LOG_DIR/result.json"

echo "Result: pass=$pass fail=$fail" | tee -a "$LOG_DIR/summary.txt"
[[ "$FAIL" -eq 0 ]]
