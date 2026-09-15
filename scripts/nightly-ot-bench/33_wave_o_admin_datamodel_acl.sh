#!/usr/bin/env bash
# Wave O8/O9 — hub-admin CRUD ACL + session-config / data-model building ACL.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/scripts/nightly-ot-bench/_common.sh" 2>/dev/null || true

ART="${ARTIFACT_DIR:-$ROOT/reports/wave_o_admin_acl_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$ART"
BASE="${OPENFDD_API_BASE:-${RAILWAY_BASE:-}}"
[[ -n "$BASE" ]] || { echo "set OPENFDD_API_BASE or RAILWAY_BASE" >&2; exit 1; }
BASE="${BASE%/}"

login() {
  local user="$1" pass="$2"
  curl -sf -X POST "$BASE/api/auth/login" \
    -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg u "$user" --arg p "$pass" '{username:$u,password:$p}')" \
    | jq -r '.token // .access_token // empty'
}

code_for() {
  local method="$1" path="$2" token="$3"
  shift 3
  curl -s -o "$ART/last.json" -w '%{http_code}' -X "$method" \
    -H "Authorization: Bearer $token" \
    -H 'Content-Type: application/json' \
    "$@" \
    "$BASE$path"
}

health="$(curl -sf "$BASE/api/health")"
echo "$health" | tee "$ART/health.json"
echo "$health" | jq -e '.multi_tenant == true' >/dev/null \
  || { echo "FAIL: multi_tenant!=true"; exit 1; }

: >"$ART/acl.log"
fail=0

ADMIN_TOKEN="$(login admin "${OPENFDD_ADMIN_PASSWORD:?}")"
[[ -n "$ADMIN_TOKEN" ]] || { echo "FAIL: admin login"; exit 1; }

ACME_TOKEN="${ACME_TOKEN:-}"
if [[ -z "$ACME_TOKEN" && -n "${OPENFDD_USER_ACME_OPS_PASSWORD:-}" ]]; then
  ACME_TOKEN="$(login acme-ops "$OPENFDD_USER_ACME_OPS_PASSWORD" || true)"
fi
if [[ -z "$ACME_TOKEN" ]]; then
  ACME_TOKEN="$(curl -sf -X POST "$BASE/api/auth/agent-token" \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H 'Content-Type: application/json' \
    -d '{"ttl_secs":1800,"tenant_id":"acme"}' | jq -r '.token // .access_token')"
fi
[[ -n "$ACME_TOKEN" ]] || { echo "FAIL: no acme token"; exit 1; }

# --- O8: hub admin can list users/tenants ---
c="$(code_for GET /api/admin/users "$ADMIN_TOKEN")"
if [[ "$c" != "200" ]]; then
  echo "FAIL: admin GET /api/admin/users got $c" | tee -a "$ART/acl.log"
  fail=1
else
  echo "PASS: admin lists users" | tee -a "$ART/acl.log"
fi
c="$(code_for GET /api/admin/tenants "$ADMIN_TOKEN")"
if [[ "$c" != "200" ]]; then
  echo "FAIL: admin GET /api/admin/tenants got $c" | tee -a "$ART/acl.log"
  fail=1
else
  echo "PASS: admin lists tenants" | tee -a "$ART/acl.log"
fi

# --- O8: tenant token cannot hit admin ---
for path in /api/admin/users /api/admin/tenants /api/admin/historian-limits; do
  c="$(code_for GET "$path" "$ACME_TOKEN")"
  if [[ "$c" != "403" && "$c" != "401" ]]; then
    echo "FAIL: acme GET $path expected 403, got $c" | tee -a "$ART/acl.log"
    fail=1
  else
    echo "PASS: acme denied $path ($c)" | tee -a "$ART/acl.log"
  fi
done
c="$(code_for PUT /api/admin/users "$ACME_TOKEN" \
  -d '{"username":"evil","role":"operator","tenant_ids":["acme"],"password":"x"}')"
if [[ "$c" != "403" && "$c" != "401" ]]; then
  echo "FAIL: acme PUT /api/admin/users expected 403, got $c" | tee -a "$ART/acl.log"
  fail=1
else
  echo "PASS: acme denied user upsert ($c)" | tee -a "$ART/acl.log"
fi

# Wave O2: mass-assign role=admin must hard-reject for hub admin PUT.
c="$(code_for PUT /api/admin/users "$ADMIN_TOKEN" \
  -d '{"username":"massassignprobe","role":"admin","tenant_ids":[],"password":"ProbePass9!"}')"
if [[ "$c" != "400" && "$c" != "403" ]]; then
  echo "FAIL: mass-assign role=admin expected 400/403, got $c" | tee -a "$ART/acl.log"
  fail=1
else
  echo "PASS: mass-assign role=admin rejected ($c)" | tee -a "$ART/acl.log"
fi

# Hub admin can read historian limits (O6).
c="$(code_for GET /api/admin/historian-limits "$ADMIN_TOKEN")"
if [[ "$c" != "200" ]]; then
  echo "FAIL: admin GET /api/admin/historian-limits got $c" | tee -a "$ART/acl.log"
  fail=1
else
  echo "PASS: admin historian-limits 200" | tee -a "$ART/acl.log"
fi

# --- O9: foreign mapping + session-config ---
c="$(code_for GET '/api/csv/import/package/mapping?building_id=BUILDING_100' "$ACME_TOKEN")"
if [[ "$c" != "403" && "$c" != "401" ]]; then
  echo "FAIL: acme mapping BUILDING_100 expected 403, got $c" | tee -a "$ART/acl.log"
  fail=1
else
  echo "PASS: acme denied foreign mapping ($c)" | tee -a "$ART/acl.log"
fi

c="$(code_for GET '/api/fdd/session-config?building_id=BUILDING_100' "$ACME_TOKEN")"
if [[ "$c" != "403" && "$c" != "401" ]]; then
  echo "FAIL: acme session-config BUILDING_100 expected 403, got $c" | tee -a "$ART/acl.log"
  fail=1
else
  echo "PASS: acme denied foreign session-config ($c)" | tee -a "$ART/acl.log"
fi

c="$(code_for GET '/api/fdd/session-config' "$ACME_TOKEN")"
if [[ "$c" != "403" && "$c" != "401" ]]; then
  echo "FAIL: acme session-config without building_id expected 403, got $c" | tee -a "$ART/acl.log"
  fail=1
else
  echo "PASS: acme denied unscoped session-config ($c)" | tee -a "$ART/acl.log"
fi

# Own-site session-config (ACME building id may be ACME)
c="$(code_for GET '/api/fdd/session-config?building_id=ACME' "$ACME_TOKEN")"
if [[ "$c" != "200" ]]; then
  echo "WARN: acme session-config ACME got $c (may lack membership stamp)" | tee -a "$ART/acl.log"
else
  echo "PASS: acme session-config ACME 200" | tee -a "$ART/acl.log"
fi

# Ephemeral user create → disable → login fail → delete (lab)
EPHEM="o8probe$(date +%s | tail -c 5)"
c="$(code_for PUT /api/admin/users "$ADMIN_TOKEN" \
  -d "$(jq -nc --arg u "$EPHEM" '{username:$u,role:"viewer",tenant_ids:["acme"],password:"ProbePass9!",disabled:false}')")"
if [[ "$c" != "200" ]]; then
  echo "FAIL: admin create $EPHEM got $c" | tee -a "$ART/acl.log"
  fail=1
else
  tok="$(login "$EPHEM" "ProbePass9!" || true)"
  if [[ -z "$tok" ]]; then
    echo "FAIL: ephemeral login before disable" | tee -a "$ART/acl.log"
    fail=1
  else
    echo "PASS: ephemeral login before disable" | tee -a "$ART/acl.log"
  fi
  code_for POST "/api/admin/users/${EPHEM}/disabled" "$ADMIN_TOKEN" -d '{"disabled":true}' >/dev/null
  tok2="$(login "$EPHEM" "ProbePass9!" || true)"
  if [[ -n "$tok2" ]]; then
    echo "FAIL: disabled user still logs in" | tee -a "$ART/acl.log"
    fail=1
  else
    echo "PASS: disabled user cannot login" | tee -a "$ART/acl.log"
  fi
  code_for DELETE "/api/admin/users/${EPHEM}" "$ADMIN_TOKEN" >/dev/null || true
fi

jq -n --argjson fail "$fail" '{ok: ($fail==0), gate:"wave_o_admin_acl", artifact:"'"$ART"'"}' \
  | tee "$ART/acl_verdict.json"
exit "$fail"
