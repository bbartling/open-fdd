#!/usr/bin/env bash
# Validate JWT roles: integrator, agent, operator — login + permission boundaries.
#
#   cd /home/ben/open-fdd && ./scripts/openfdd_auth_rbac_validate.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_auth_lib.sh
source "$ROOT/scripts/openfdd_auth_lib.sh"
# shellcheck source=scripts/openfdd_bench_lib.sh
source "$ROOT/scripts/openfdd_bench_lib.sh"

openfdd_bench_load_profile "$ROOT" || true

BASE="${OPENFDD_API_BASE:-http://127.0.0.1:8080}"
AUTH="${OPENFDD_AUTH_ENV:-$ROOT/workspace/auth.env.local}"
RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_DIR="${OPENFDD_RBAC_DIR:-$ROOT/workspace/logs/rbac_eval_${RUN_TS}}"
mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_DIR/rbac.log") 2>&1

pass=0 fail=0 skip=0 FAIL=0
check() {
  openfdd_bench_check_line "$1" "$2" "$3" "$LOG_DIR/summary.txt"
  case "$2" in pass) pass=$((pass + 1)) ;; skip) skip=$((skip + 1)) ;; *) fail=$((fail + 1)); FAIL=1 ;; esac
}

: >"$LOG_DIR/summary.txt"
CURL_TLS=()
[[ "$BASE" == https://* ]] && CURL_TLS=(-k)

http_code() {
  local token="$1" method="$2" path="$3" body="${4:-}"
  if [[ -n "$body" ]]; then
    curl "${CURL_TLS[@]}" -sS -o "$LOG_DIR/last.json" -w '%{http_code}' \
      -X "$method" -H "Authorization: Bearer $token" -H 'Content-Type: application/json' \
      -d "$body" "${BASE}${path}" 2>/dev/null || echo 000
  else
    curl "${CURL_TLS[@]}" -sS -o "$LOG_DIR/last.json" -w '%{http_code}' \
      -X "$method" -H "Authorization: Bearer $token" \
      "${BASE}${path}" 2>/dev/null || echo 000
  fi
}

declare -A TOKENS=()

for role in admin integrator agent operator; do
  if tok="$(openfdd_auth_login_token "$BASE" "$AUTH" "$role" 2>/dev/null)" && [[ -n "$tok" ]]; then
    TOKENS[$role]="$tok"
    check "login-$role" pass "JWT obtained"
    me="$(curl "${CURL_TLS[@]}" -fsS -H "Authorization: Bearer $tok" "$BASE/api/auth/me" 2>/dev/null || echo '{}')"
    echo "$me" >"$LOG_DIR/auth_me_${role}.json"
    got_role="$(jq -r '.role // empty' <<< "$me")"
    if [[ "$got_role" == "$role" ]]; then
      check "auth-me-$role" pass "role=$got_role"
    else
      check "auth-me-$role" fail "expected $role got '$got_role'"
    fi
  else
    check "login-$role" fail "login failed — run openfdd_auth_init.sh --rotate --all"
  fi
done

# Read paths — all roles should reach stack health + driver trees
for role in admin integrator agent operator; do
  tok="${TOKENS[$role]:-}"
  [[ -n "$tok" ]] || continue
  for spec in "GET:/api/health/stack" "GET:/api/bacnet/driver/tree" "GET:/api/modbus/driver/tree"; do
    IFS=: read -r meth path <<< "$spec"
    code="$(http_code "$tok" "$meth" "$path")"
    if [[ "$code" =~ ^2 ]]; then
      check "read-${role}-$(basename "$path")" pass "HTTP $code"
    else
      check "read-${role}-$(basename "$path")" fail "HTTP $code"
    fi
  done
done

# Integrator-only mutating route (CSV import job create)
for role in admin integrator agent operator; do
  tok="${TOKENS[$role]:-}"
  [[ -n "$tok" ]] || continue
  code="$(http_code "$tok" POST /api/import/jobs '{"source_type":"csv","label":"rbac-smoke"}')"
  case "$role" in
    integrator|agent)
      [[ "$code" =~ ^2 ]] && check "import-create-$role" pass "HTTP $code (allowed)" \
        || check "import-create-$role" fail "HTTP $code expected 2xx"
      ;;
    admin)
      if [[ "$code" =~ ^2 ]]; then
        check "import-create-$role" pass "HTTP $code (allowed)"
      elif [[ "$code" == "403" ]]; then
        check "import-create-$role" pass "HTTP 403 (admin is auth-only — expected boundary)"
      else
        check "import-create-$role" fail "HTTP $code"
      fi
      ;;
    operator)
      if [[ "$code" == "403" ]]; then
        err="$(jq -r '.error // empty' "$LOG_DIR/last.json" 2>/dev/null)"
        [[ "$err" == *insufficient* ]] && check "import-create-operator-denied" pass "HTTP 403 insufficient role" \
          || check "import-create-operator-denied" pass "HTTP 403 denied"
      else
        check "import-create-operator-denied" fail "operator must not create imports (got HTTP $code)"
      fi
      ;;
  esac
done

# Agent FDD cycle — optional when validation run active
if [[ -n "${TOKENS[agent]:-}" ]]; then
  code="$(http_code "${TOKENS[agent]}" POST /api/validation-runs/current/cycle '{}')"
  if [[ "$code" == "404" ]]; then
    check "agent-fdd-cycle" skip "no active validation run (HTTP 404)"
  elif [[ "$code" =~ ^2 ]]; then
    check "agent-fdd-cycle" pass "HTTP $code"
  else
    check "agent-fdd-cycle" fail "HTTP $code"
  fi
fi

jq -nc --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg dir "$LOG_DIR" \
  --argjson pass "$pass" --argjson fail "$fail" --argjson skip "$skip" \
  '{timestamp_utc:$ts,artifact_dir:$dir,pass_count:$pass,fail_count:$fail,skip_count:$skip,ok:($fail==0)}' \
  >"$LOG_DIR/result.json"

echo "$LOG_DIR" >"$ROOT/workspace/logs/rbac_eval_latest.dir"
ln -sfn "$LOG_DIR" "$ROOT/workspace/logs/rbac_eval_latest" 2>/dev/null || true

echo "RBAC eval: pass=$pass fail=$fail skip=$skip → $LOG_DIR"
[[ "$FAIL" -eq 0 ]]
