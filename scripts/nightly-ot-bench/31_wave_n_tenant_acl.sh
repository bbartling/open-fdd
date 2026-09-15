#!/usr/bin/env bash
# Wave N — pairwise tenant ACL gate (ACME / building_100 / lakeside_sd).
# Requires OPENFDD_MULTI_TENANT=1 and provisioned file users (or admin-minted scoped tokens).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/scripts/nightly-ot-bench/_common.sh" 2>/dev/null || true

ART="${ARTIFACT_DIR:-$ROOT/reports/wave_n_acl_$(date -u +%Y%m%dT%H%M%SZ)}"
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

deny_building() {
  local token="$1" bid="$2" label="$3"
  local code
  code="$(curl -s -o "$ART/${label}_buildings.json" -w '%{http_code}' \
    -H "Authorization: Bearer $token" \
    "$BASE/api/tenants")"
  # List may be 200 but buildings_visible must not include foreign building.
  if jq -e --arg b "$bid" '
      (.buildings_visible // []) | index($b)
    ' "$ART/${label}_buildings.json" >/dev/null 2>&1; then
    echo "FAIL: $label can see building $bid" | tee -a "$ART/acl.log"
    return 1
  fi
  # Explicit select of foreign tenant must be 403
  local sel
  sel="$(curl -s -o "$ART/${label}_select.json" -w '%{http_code}' \
    -X POST -H "Authorization: Bearer $token" -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg t "$4" '{tenant_id:$t}')" \
    "$BASE/api/tenants/select")"
  if [[ "$sel" != "403" && "$sel" != "401" ]]; then
    echo "FAIL: $label select foreign tenant expected 403, got $sel" | tee -a "$ART/acl.log"
    return 1
  fi
  # Data-path ACL: mapping + FDD series must not leak foreign buildings (Wave N).
  local map_code series_code
  map_code="$(curl -s -o "$ART/${label}_map_${bid}.json" -w '%{http_code}' \
    -H "Authorization: Bearer $token" \
    "$BASE/api/csv/import/package/mapping?building_id=${bid}")"
  if [[ "$map_code" != "403" && "$map_code" != "401" ]]; then
    echo "FAIL: $label mapping foreign building $bid expected 403, got $map_code" | tee -a "$ART/acl.log"
    return 1
  fi
  series_code="$(curl -s -o "$ART/${label}_series_${bid}.json" -w '%{http_code}' \
    -H "Authorization: Bearer $token" \
    "$BASE/api/fdd/series?building_id=${bid}&equipment_id=AHU_1&rule_id=FC1")"
  if [[ "$series_code" != "403" && "$series_code" != "401" ]]; then
    echo "FAIL: $label fdd/series foreign building $bid expected 403, got $series_code" | tee -a "$ART/acl.log"
    return 1
  fi
  # Wave O1: package write paths must fail closed like reads.
  local append_code
  append_code="$(curl -s -o "$ART/${label}_append_${bid}.json" -w '%{http_code}' \
    -X POST -H "Authorization: Bearer $token" -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg b "$bid" '{confirm:true,building_id:$b,equipment_id:"AHU_1",csv:"timestamp_utc,x\n2026-01-01T00:00:00Z,1\n"}')" \
    "$BASE/api/csv/import/package/append")"
  if [[ "$append_code" != "403" && "$append_code" != "401" ]]; then
    echo "FAIL: $label package append foreign building $bid expected 403, got $append_code" | tee -a "$ART/acl.log"
    return 1
  fi
  echo "PASS: $label denied $bid / tenant $4 (list+select+mapping+series+append)" | tee -a "$ART/acl.log"
  return 0
}

health="$(curl -sf "$BASE/api/health")"
echo "$health" | tee "$ART/health.json"
echo "$health" | jq -e '.multi_tenant == true' >/dev/null \
  || { echo "FAIL: multi_tenant!=true"; exit 1; }

: >"$ART/acl.log"
fail=0

# Prefer file users; fall back to admin-minted scoped agent tokens.
ADMIN_TOKEN="$(login admin "${OPENFDD_ADMIN_PASSWORD:?}")"
ACME_TOKEN="${ACME_TOKEN:-}"
B100_TOKEN="${B100_TOKEN:-}"
LAKE_TOKEN="${LAKE_TOKEN:-}"

if [[ -z "$ACME_TOKEN" && -n "${OPENFDD_USER_ACME_OPS_PASSWORD:-}" ]]; then
  ACME_TOKEN="$(login acme-ops "$OPENFDD_USER_ACME_OPS_PASSWORD")"
fi
if [[ -z "$B100_TOKEN" && -n "${OPENFDD_USER_B100_OPS_PASSWORD:-}" ]]; then
  B100_TOKEN="$(login b100-ops "$OPENFDD_USER_B100_OPS_PASSWORD")"
fi
if [[ -z "$LAKE_TOKEN" && -n "${OPENFDD_USER_LAKESIDE_OPS_PASSWORD:-}" ]]; then
  LAKE_TOKEN="$(login lakeside-ops "$OPENFDD_USER_LAKESIDE_OPS_PASSWORD")"
fi

mint_scoped() {
  local tid="$1"
  curl -sf -X POST "$BASE/api/auth/agent-token" \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg t "$tid" '{ttl_secs:1800,tenant_id:$t}')" \
    | jq -r '.token // .access_token'
}

[[ -n "$ACME_TOKEN" ]] || ACME_TOKEN="$(mint_scoped acme)"
[[ -n "$B100_TOKEN" ]] || B100_TOKEN="$(mint_scoped building_100)"
[[ -n "$LAKE_TOKEN" ]] || LAKE_TOKEN="$(mint_scoped lakeside_sd)"

deny_building "$ACME_TOKEN" "BUILDING_100" "acme" "building_100" || fail=1
deny_building "$ACME_TOKEN" "LAKESIDE_ES" "acme" "lakeside_sd" || fail=1
deny_building "$B100_TOKEN" "ACME" "b100" "acme" || fail=1
deny_building "$B100_TOKEN" "LAKESIDE_ES" "b100" "lakeside_sd" || fail=1
deny_building "$LAKE_TOKEN" "ACME" "lake" "acme" || fail=1
deny_building "$LAKE_TOKEN" "BUILDING_100" "lake" "building_100" || fail=1

# Admin can list all three tenants
admin_tenants="$(curl -sf -H "Authorization: Bearer $ADMIN_TOKEN" "$BASE/api/tenants")"
echo "$admin_tenants" | tee "$ART/admin_tenants.json"
echo "$admin_tenants" | jq -e '
  (.tenants | map(.id)) as $ids
  | ($ids | index("acme")) and ($ids | index("building_100")) and ($ids | index("lakeside_sd"))
' >/dev/null || { echo "FAIL: admin missing tenants"; fail=1; }
echo "PASS: admin lists acme+building_100+lakeside_sd" | tee -a "$ART/acl.log"

jq -n --argjson fail "$fail" '{ok: ($fail==0), gate:"wave_n_acl", artifact:"'"$ART"'"}' \
  | tee "$ART/acl_verdict.json"
exit "$fail"
