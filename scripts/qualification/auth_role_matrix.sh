#!/usr/bin/env bash
# Railway / remote auth×role matrix (deterministic; not ZAP).
# Roles in product: anonymous, viewer (JWT-minted only if secret available),
# operator (agent password), admin (admin password).
# Does not invent tenant/building isolation — documents deployment-wide access.
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
if [[ -z "${OPENFDD_ADMIN_PASSWORD:-}" ]]; then
  echo "ERROR: OPENFDD_ADMIN_PASSWORD required" >&2
  exit 1
fi

code_of() {
  local method="$1" url="$2" token="${3:-}" body="${4:-}"
  local args=(-sS -o /tmp/auth_matrix_body.$$ -w "%{http_code}" --max-time 25 -X "$method")
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
na_n=0

record() {
  local id="$1" expect="$2" got="$3" note="$4"
  local st="PASS"
  if [[ "$expect" == "N/A" ]]; then
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
  c="$(code_of GET "$BASE/api/edges" "$ADMIN_TOK")"
  record "admin_edges" "200" "$c" "admin can read edges"
  c="$(code_of GET "$BASE/api/fdd/rules" "$ADMIN_TOK")"
  record "admin_fdd_rules" "200" "$c" "admin can read FDD"
  c="$(code_of POST "$BASE/api/auth/agent-token" "$ADMIN_TOK" '{}')"
  # 200 mint or 200 with token body
  if [[ "$c" == "200" ]]; then
    record "admin_agent_token" "200" "$c" "admin may mint operator JWT"
  else
    record "admin_agent_token" "200" "$c" "admin agent-token mint"
  fi
fi

# --- operator (agent password) ---
if [[ -n "${OPENFDD_AGENT_PASSWORD:-${RAILWAY_AGENT_PASSWORD:-}}" ]]; then
  AGENT_PW="${OPENFDD_AGENT_PASSWORD:-$RAILWAY_AGENT_PASSWORD}"
  OP_TOK="$(login agent "$AGENT_PW" || true)"
  if [[ -z "$OP_TOK" ]]; then
    record "operator_login" "token" "empty" "agent login failed"
  else
    record "operator_login" "token" "token" "agent → operator JWT"
    c="$(code_of GET "$BASE/api/edges" "$OP_TOK")"
    record "operator_edges" "200" "$c" "operator can read edges"
    c="$(code_of POST "$BASE/api/auth/agent-token" "$OP_TOK" '{}')"
    record "operator_agent_token" "403" "$c" "operator cannot mint agent-token"
  fi
else
  record "operator_login" "N/A" "N/A" "OPENFDD_AGENT_PASSWORD unset — operator path not exercised"
fi

# --- viewer: password login does not exist; mint only with JWT secret (local/disposable) ---
if [[ -n "${OPENFDD_JWT_SECRET:-}" ]] && command -v python3 >/dev/null; then
  VIEW_TOK="$(
    OPENFDD_JWT_SECRET="$OPENFDD_JWT_SECRET" python3 - <<'PY'
import os, time, hmac, hashlib, base64, json
secret=os.environ["OPENFDD_JWT_SECRET"].encode()
def b64(d):
    return base64.urlsafe_b64encode(d).rstrip(b"=").decode()
header=b64(json.dumps({"alg":"HS256","typ":"JWT"}).encode())
payload=b64(json.dumps({
  "sub":"viewer-matrix","role":"viewer","iat":int(time.time()),
  "exp":int(time.time())+600
}).encode())
msg=f"{header}.{payload}".encode()
sig=b64(hmac.new(secret, msg, hashlib.sha256).digest())
print(f"{header}.{payload}.{sig}")
PY
  )"
  c="$(code_of GET "$BASE/api/edges" "$VIEW_TOK")"
  # Railway may reject tokens signed with a different secret → treat non-200 as BLOCKED path
  if [[ "$c" == "200" ]]; then
    record "viewer_edges" "200" "$c" "viewer JWT (same secret) can read"
    c="$(code_of POST "$BASE/api/auth/agent-token" "$VIEW_TOK" '{}')"
    record "viewer_agent_token" "403" "$c" "viewer cannot mint agent-token"
  else
    record "viewer_edges" "N/A" "$c" "viewer JWT rejected (secret mismatch or auth off) — Railway password login has no viewer user"
  fi
else
  record "viewer_edges" "N/A" "N/A" "no OPENFDD_JWT_SECRET — viewer not password-loginable; deployment-wide RBAC only for admin/agent"
fi

# limitation note
LIMIT="Users currently authenticate as admin or agent (operator). Viewer exists in RBAC but is not a password login identity on Railway. Access is deployment-wide (no tenant/building claim isolation tested here)."

jq -n \
  --arg base "$BASE" \
  --arg limit "$LIMIT" \
  --argjson pass "$pass_n" \
  --argjson fail "$fail_n" \
  --argjson na "$na_n" \
  --argjson results "$(printf '%s\n' "${RESULTS[@]}" | jq -s .)" \
  '{base:$base,limitation:$limit,pass:$pass,fail:$fail,not_applicable:$na,results:$results}' \
  >"$OUT"

echo "Wrote $OUT (pass=$pass_n fail=$fail_n na=$na_n)"
if [[ "$fail_n" -gt 0 ]]; then
  exit 1
fi
exit 0
