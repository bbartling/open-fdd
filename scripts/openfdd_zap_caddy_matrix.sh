#!/usr/bin/env bash
# ZAP + Caddy matrix — direct :8080, caddy-http :80, caddy-tls :443 (TLS + non-TLS bootstrap).
#
#   ./scripts/openfdd_zap_caddy_matrix.sh
#   OPENFDD_ZAP_MATRIX_DIR=... ./scripts/openfdd_zap_caddy_matrix.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_bench_lib.sh
source "$ROOT/scripts/openfdd_bench_lib.sh"

openfdd_bench_load_profile "$ROOT" || true

RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_DIR="${OPENFDD_ZAP_MATRIX_DIR:-$ROOT/workspace/logs/zap_caddy_matrix_${RUN_TS}}"
BRIDGE="${OPENFDD_API_BASE:-http://127.0.0.1:8080}"
CADDY_HTTP="${OPENFDD_CADDY_HTTP_BASE:-http://127.0.0.1:${OPENFDD_CADDY_HTTP_PORT:-80}}"
CADDY_TLS="${OPENFDD_CADDY_TLS_BASE:-https://127.0.0.1:${OPENFDD_CADDY_HTTPS_PORT:-443}}"
RESTORE="${OPENFDD_CADDY_RESTORE_DIRECT:-1}"
MAX_MINS="${OPENFDD_ZAP_MAX_MINUTES:-10}"

mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_DIR/matrix.log") 2>&1

pass=0 fail=0 FAIL=0
log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }
check() {
  openfdd_bench_check_line "$1" "$2" "$3" "$LOG_DIR/summary.txt"
  if [[ "$2" == pass ]]; then pass=$((pass + 1)); else fail=$((fail + 1)); FAIL=1; fi
}

: >"$LOG_DIR/summary.txt"
log "=== ZAP + Caddy ingress matrix → $LOG_DIR ==="

run_scenario() {
  local name="$1" recipe="$2" target="$3" tls="$4"
  local sdir="$LOG_DIR/$name"
  mkdir -p "$sdir"

  log "--- Scenario: $name (recipe=$recipe target=$target) ---"

  if [[ "$recipe" != "none" ]]; then
    if ! "$ROOT/scripts/openfdd_caddy_test_recipe.sh" "$recipe" 2>&1 | tee "$sdir/recipe.log"; then
      check "recipe-$name" fail "caddy recipe $recipe failed"
      return 1
    fi
    check "recipe-$name" pass "bootstrap $recipe"
  else
    "$ROOT/scripts/openfdd_caddy_test_recipe.sh" direct 2>&1 | tee "$sdir/recipe.log" || true
  fi

  if [[ "$recipe" != "none" && "$recipe" != "direct" ]]; then
    export OPENFDD_BRIDGE_BASE="$BRIDGE"
    export OPENFDD_CADDY_HTTP_BASE="$CADDY_HTTP"
    export OPENFDD_CADDY_TLS_BASE="$CADDY_TLS"
    if "$ROOT/scripts/openfdd_caddy_validate.sh" 2>&1 | tee "$sdir/caddy_validate.log"; then
      check "caddy-validate-$name" pass "openfdd_caddy_validate.sh"
    else
      check "caddy-validate-$name" fail "Caddy validation failed"
    fi
  else
    check "caddy-validate-$name" skip "direct bridge — no Caddy profile"
  fi

  export OPENFDD_ZAP_TARGET="$target"
  export OPENFDD_ZAP_LABEL="$name"
  export OPENFDD_ZAP_OUT_DIR="$sdir/zap"
  export OPENFDD_ZAP_TLS_INSECURE="$tls"
  export OPENFDD_ZAP_MAX_MINUTES="$MAX_MINS"
  unset OPENFDD_ZAP_AUTH_HEADER || true

  if "$ROOT/scripts/openfdd_zap_scan.sh" 2>&1 | tee "$sdir/zap_run.log"; then
    check "zap-$name" pass "ZAP baseline $target"
  else
    check "zap-$name" fail "ZAP baseline $target (CORS/auth/headers — see zap_report.md)"
  fi
  return 0
}

# 1) Direct bridge (non-TLS lab bootstrap — default bench)
run_scenario "bootstrap-direct" "direct" "$BRIDGE" "0"

# 2) Caddy HTTP (:80 LAN ingress, non-TLS)
run_scenario "bootstrap-caddy-http" "caddy-http" "$CADDY_HTTP" "0"

# 3) Caddy TLS (:443 self-signed, :80 redirect)
run_scenario "bootstrap-caddy-tls" "caddy-tls" "$CADDY_TLS" "1"

if [[ "$RESTORE" == "1" ]]; then
  log "Restoring direct bench (stop Caddy)"
  "$ROOT/scripts/openfdd_caddy_test_recipe.sh" direct || true
fi

# shellcheck source=scripts/openfdd_rust_site_lib.sh
source "$ROOT/scripts/openfdd_rust_site_lib.sh"
openfdd_rust_ensure_bridge_host_network "$ROOT" "$BRIDGE/api/health" || true

# Matrix summary for issue #411 / patch zip
jq -nc \
  --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg dir "$LOG_DIR" \
  --argjson pass "$pass" --argjson fail "$fail" \
  --slurpfile d "$LOG_DIR/bootstrap-direct/zap/zap_result.json" \
  --slurpfile h "$LOG_DIR/bootstrap-caddy-http/zap/zap_result.json" \
  --slurpfile t "$LOG_DIR/bootstrap-caddy-tls/zap/zap_result.json" \
  '{
    timestamp_utc: $ts,
    artifact_dir: $dir,
    pass_count: $pass,
    fail_count: $fail,
    scenarios: {
      direct: ($d[0] // {}),
      caddy_http: ($h[0] // {}),
      caddy_tls: ($t[0] // {})
    },
    ok: ($fail == 0)
  }' >"$LOG_DIR/zap_matrix_result.json" 2>/dev/null || \
  jq -nc --arg dir "$LOG_DIR" --argjson fail "$fail" '{artifact_dir:$dir,ok:($fail==0)}' >"$LOG_DIR/zap_matrix_result.json"

cat >"$LOG_DIR/ZAP_MATRIX_README.md" <<EOF
# ZAP ingress matrix

| Scenario | Bootstrap recipe | ZAP target | TLS |
|----------|------------------|------------|-----|
| bootstrap-direct | \`direct\` (no Caddy) | ${BRIDGE} | no |
| bootstrap-caddy-http | \`caddy-http\` | ${CADDY_HTTP} | no |
| bootstrap-caddy-tls | \`caddy-tls\` + self-signed certs | ${CADDY_TLS} | yes (\`-k\` / trustAll) |

Each scenario runs \`openfdd_caddy_validate.sh\` then \`openfdd_zap_scan.sh\`.
Check \`*/zap/zap_report.md\` for CORS, auth headers, security headers on \`/api/*\`.
EOF

echo | tee -a "$LOG_DIR/summary.txt"
echo "Result: pass=$pass fail=$fail artifact=$LOG_DIR" | tee -a "$LOG_DIR/summary.txt"
log "=== ZAP matrix DONE fail=$FAIL ==="
[[ "$FAIL" -eq 0 ]]
