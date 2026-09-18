#!/usr/bin/env bash
# Railway / remote auth×role matrix (deterministic; not ZAP).
# Roles: anonymous, viewer (OPENFDD_VIEWER_PASSWORD login), operator (agent), admin.
# Missing configured credentials are BLOCKED (never N/A).
# Does not invent tenant/building isolation — documents deployment-wide RBAC smoke.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$DIR/../.." && pwd)"
BASE="${OPENFDD_API_BASE:-${RAILWAY_BASE:-}}"
ART="${ARTIFACT_DIR:-$ROOT/reports/auth-matrix_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$ART"
OUT="$ART/auth_role_matrix.json"

if [[ -z "$BASE" ]]; then
  echo "ERROR: OPENFDD_API_BASE / RAILWAY_BASE required" >&2
  exit 1
fi
if [[ "$BASE" != https://* && "$BASE" != http://127.0.0.1* && "$BASE" != http://localhost* ]]; then
  echo "ERROR: auth role matrix requires https:// hub or loopback http, got: $BASE" >&2
  exit 1
fi
if [[ -z "${OPENFDD_ADMIN_PASSWORD:-}" ]]; then
  echo "ERROR: OPENFDD_ADMIN_PASSWORD required" >&2
  exit 1
fi

code_of() {
  local method="$1" url="$2" token="${3:-}" body="${4:-}"
  local args=(-sS -o /dev/null -w "%{http_code}" --max-time 25 -X "$method")
  [[ -n "$token" ]] && args+=(-H "Authorization: Bearer $token")
  if [[ -n "$body" ]]; then
    args+=(-H "Content-Type: application/json" -d "$body")
  fi
  curl "${args[@]}" "$url" || echo "000"
}

login() {
  local user="$1" pass="$2"
  curl -sf --max-time 25 -X POST "$BASE/api/auth/login" \
    -H "Content-Type: application/json" \
    -d "$(jq -nc --arg u "$user" --arg p "$pass" '{username:$u,password:$p}')" \
    | jq -r '.token // empty'
}

declare -a RESULTS=()
pass_n=0
fail_n=0
blocked_n=0
na_n=0

record() {
  local id="$1" expect="$2" got="$3" note="$4"
  local st="PASS"
  if [[ "$expect" == "BLOCKED" ]]; then
    st="BLOCKED"
    blocked_n=$((blocked_n + 1))
  elif [[ "$expect" == "N/A" ]]; then
    st="NOT_APPLICABLE"
    na_n=$((na_n + 1))
  elif [[ "$got" == "$expect" ]]; then
    pass_n=$((pass_n + 1))
  else
    st="FAIL"
    fail_n=$((fail_n + 1))
  fi
  RESULTS+=("$(jq -nc --arg id "$id" --arg st "$st" --arg exp "$expect" --arg got "$got" --arg note "$note" \
    '{id:$id,status:$st,expect:$exp,got:$got,note:$note}')")
  echo "[$st] $id expect=$expect got=$got — $note"
}

# --- anonymous ---
c="$(code_of GET "$BASE/api/health")"
record "anon_health" "200" "$c" "health is public"
c="$(code_of GET "$BASE/api/edges")"
record "anon_edges" "401" "$c" "edges require auth"
c="$(code_of GET "$BASE/api/fdd/rules")"
record "anon_fdd_rules" "401" "$c" "FDD rules require auth"
c="$(code_of POST "$BASE/api/auth/agent-token" "" '{}')"
record "anon_agent_token" "401" "$c" "agent-token mint requires auth"

# --- admin ---
ADMIN_TOK="$(login admin "$OPENFDD_ADMIN_PASSWORD" || true)"
if [[ -z "$ADMIN_TOK" ]]; then
  record "admin_login" "token" "empty" "admin login failed"
else
  record "admin_login" "token" "token" "admin JWT minted"
  me="$(curl -sf --max-time 25 -H "Authorization: Bearer $ADMIN_TOK" "$BASE/api/auth/me" || true)"
  role="$(echo "$me" | jq -r '.role // empty')"
  if [[ "$role" == "admin" ]]; then
    record "admin_me" "admin" "$role" "/api/auth/me role"
  else
    record "admin_me" "admin" "${role:-empty}" "/api/auth/me role mismatch"
  fi
  c="$(code_of GET "$BASE/api/edges" "$ADMIN_TOK")"
  record "admin_edges" "200" "$c" "admin can read edges"
  c="$(code_of GET "$BASE/api/fdd/rules" "$ADMIN_TOK")"
  record "admin_fdd_rules" "200" "$c" "admin can read FDD"
  c="$(code_of POST "$BASE/api/auth/agent-token" "$ADMIN_TOK" '{}')"
  record "admin_agent_token" "200" "$c" "admin may mint operator JWT"
fi

# --- operator (agent password) — missing creds = BLOCKED ---
if [[ -n "${OPENFDD_AGENT_PASSWORD:-${RAILWAY_AGENT_PASSWORD:-}}" ]]; then
  AGENT_PW="${OPENFDD_AGENT_PASSWORD:-$RAILWAY_AGENT_PASSWORD}"
  OP_TOK="$(login agent "$AGENT_PW" || true)"
  if [[ -z "$OP_TOK" ]]; then
    record "operator_login" "token" "empty" "agent login failed"
  else
    record "operator_login" "token" "token" "agent → operator JWT"
    me="$(curl -sf --max-time 25 -H "Authorization: Bearer $OP_TOK" "$BASE/api/auth/me" || true)"
    role="$(echo "$me" | jq -r '.role // empty')"
    if [[ "$role" == "operator" || "$role" == "admin" ]]; then
      record "operator_me" "operator" "$role" "/api/auth/me role"
    else
      record "operator_me" "operator" "${role:-empty}" "/api/auth/me unexpected role"
    fi
    c="$(code_of GET "$BASE/api/edges" "$OP_TOK")"
    record "operator_edges" "200" "$c" "operator can read edges"
    c="$(code_of POST "$BASE/api/auth/agent-token" "$OP_TOK" '{}')"
    record "operator_agent_token" "403" "$c" "operator cannot mint agent-token"
  fi
else
  record "operator_login" "BLOCKED" "BLOCKED" "OPENFDD_AGENT_PASSWORD unset — operator path BLOCKED (not N/A)"
fi

# --- viewer: password login via OPENFDD_VIEWER_PASSWORD (auth.rs) ---
if [[ -n "${OPENFDD_VIEWER_PASSWORD:-}" ]]; then
  VIEW_TOK="$(login viewer "$OPENFDD_VIEWER_PASSWORD" || true)"
  if [[ -z "$VIEW_TOK" ]]; then
    record "viewer_login" "token" "empty" "viewer password login failed"
  else
    record "viewer_login" "token" "token" "viewer JWT via password"
    me="$(curl -sf --max-time 25 -H "Authorization: Bearer $VIEW_TOK" "$BASE/api/auth/me" || true)"
    role="$(echo "$me" | jq -r '.role // empty')"
    record "viewer_me" "viewer" "${role:-empty}" "/api/auth/me role"
    c="$(code_of GET "$BASE/api/edges" "$VIEW_TOK")"
    record "viewer_edges" "200" "$c" "viewer can read edges"
    c="$(code_of POST "$BASE/api/auth/agent-token" "$VIEW_TOK" '{}')"
    record "viewer_agent_token" "403" "$c" "viewer cannot mint agent-token"
  fi
else
  record "viewer_login" "BLOCKED" "BLOCKED" "OPENFDD_VIEWER_PASSWORD unset — viewer path BLOCKED (not N/A)"
fi

LIMIT="Admin/agent/viewer password logins exercise deployment-wide RBAC. Tenant isolation is gates 20/22/25 — not this matrix."

jq -n \
  --arg base "$BASE" \
  --arg limit "$LIMIT" \
  --argjson pass "$pass_n" \
  --argjson fail "$fail_n" \
  --argjson blocked "$blocked_n" \
  --argjson na "$na_n" \
  --argjson results "$(printf '%s\n' "${RESULTS[@]}" | jq -s .)" \
  '{base:$base,limitation:$limit,pass:$pass,fail:$fail,blocked:$blocked,not_applicable:$na,results:$results}' \
  >"$OUT"

echo "Wrote $OUT (pass=$pass_n fail=$fail_n blocked=$blocked_n na=$na_n)"
if [[ "$fail_n" -gt 0 ]]; then
  exit 1
fi
if [[ "$blocked_n" -gt 0 ]]; then
  exit 2
fi
exit 0
