#!/usr/bin/env bash
# Disposable portal qualification (deployment profile `cloud_portal`).
#
# Brings up central + web + Timescale from GHCR (OPENFDD_IMAGE_TAG=sha-<7>)
# plus the loopback NF emulator, with OPENFDD_MULTI_TENANT=1 and a per-run
# random JWT secret. Creates tenants A and B with viewer and operator users
# through the admin API (qa<date> prefix), seeds one canary package per
# tenant, waits for NF emulator samples in Timescale, then runs the security
# harness (isolated_full X/Y/Z) and proves the Timescale state of both
# tenants is unchanged by the denied writes.
#
# Never builds images, never contacts Railway, a real NF portal, or a site.
# Teardown is project-scoped (see lib/portal_stack.sh).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
# shellcheck source-path=SCRIPTDIR source=lib/portal_stack.sh
source "$ROOT/scripts/qualification/lib/portal_stack.sh"

portal_require_tag
portal_preflight

ART="${ARTIFACT_DIR:-$ROOT/reports/portal_qual_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$ART"
chmod 700 "$ART"
ART="$(cd "$ART" && pwd)"

portal_stack_init portal
trap portal_stack_cleanup EXIT
portal_enable_nf

PREFIX="$PORTAL_PREFIX"
SITE_A="$(jq -r '.tenants.a.site' "$PORTAL_PLAN")"
SITE_B="$(jq -r '.tenants.b.site' "$PORTAL_PLAN")"
NF_SITE="$(jq -r '.nf.building_id' "$PORTAL_PLAN")"
echo "== Portal qualification $PREFIX (project $PORTAL_PROJECT, tag $PORTAL_TAG) =="

echo "== Pull GHCR images and start the disposable stack =="
portal_stack_up 240
portal_step stack.healthy PASS "web /api/health via 127.0.0.1:$PORTAL_WEB_PORT"

echo "== Observe services and images =="
running="$(portal_compose ps --services --status running | sort | tr '\n' ' ')"
echo "running: $running"
forbidden_hit=""
for svc in mqtt fieldbus bacnet modbus haystack; do
  if portal_compose ps -a --format '{{.Service}} {{.Image}}' | grep -qi "$svc"; then
    forbidden_hit+="$svc "
  fi
done
if [[ "$running" == *central* && "$running" == *web* && "$running" == *timescale* && "$running" == *nf-emulator* ]]; then
  portal_step deployment.services.required PASS "$running"
else
  portal_step deployment.services.required FAIL "running: $running"
fi
if [[ -z "$forbidden_hit" ]]; then
  portal_step deployment.cloud.zero_ot PASS "no mqtt/fieldbus/bacnet/modbus/haystack service in project"
else
  portal_step deployment.cloud.zero_ot FAIL "forbidden services: $forbidden_hit"
fi
images_json="$ART/images.json"
{
  echo "{"
  first=1
  for ref in "ghcr.io/bbartling/openfdd-central:$PORTAL_TAG" "ghcr.io/bbartling/openfdd-web:$PORTAL_TAG" \
    "$(docker inspect --format '{{.Config.Image}}' "$(portal_compose ps -q timescale)" 2>/dev/null || true)"; do
    [[ -n "$ref" ]] || continue
    (( first )) || echo ","
    first=0
    printf '  "%s": "%s"' "$ref" "$(portal_image_digest "$ref")"
  done
  echo
  echo "}"
} >"$images_json"
if jq -e 'to_entries | length >= 3 and all(.value | test("@sha256:[0-9a-f]{64}$"))' "$images_json" >/dev/null; then
  portal_step deployment.images.immutable PASS "repo digests recorded in images.json"
else
  portal_step deployment.images.immutable FAIL "missing repo digest (see images.json)"
fi
central_ports="$(docker port "$(portal_compose ps -q central)" 2>/dev/null || true)"
ts_ports="$(docker port "$(portal_compose ps -q timescale)" 2>/dev/null || true)"
if [[ -z "$central_ports" && -z "$ts_ports" ]]; then
  portal_step deployment.exposure.private_central_timescale PASS "central and timescale publish no host port"
else
  portal_step deployment.exposure.private_central_timescale FAIL "central=$central_ports timescale=$ts_ports"
fi
unauth_status="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$PORTAL_BASE/api/tenants" || echo 000)"
if [[ "$unauth_status" == "401" ]]; then
  portal_step deployment.auth.jwt_required PASS "anonymous /api/tenants → 401"
else
  portal_step deployment.auth.jwt_required FAIL "anonymous /api/tenants → $unauth_status"
fi

echo "== Admin login + control plane fixtures via API =="
portal_login admin admin || portal_die "admin login failed"
for side in a b; do
  jq -c --arg s "$side" '.tenants[$s] | {id, name, building_ids}' "$PORTAL_PLAN" >"$PORTAL_PRIV/tenant.$side.json"
  portal_api admin PUT /api/admin/tenants "$PORTAL_PRIV/tenant.$side.json" >/dev/null
  [[ "$(portal_last_status)" == "200" ]] || portal_die "tenant $side upsert → $(portal_last_status)"
done
tenants_seen="$(portal_api admin GET /api/admin/tenants | jq -r '[.tenants[]?.id] | join(",")')"
if [[ "$tenants_seen" == *"${PREFIX}_tenant_a"* && "$tenants_seen" == *"${PREFIX}_tenant_b"* ]]; then
  portal_step control_plane.tenants PASS "tenants A and B created via /api/admin/tenants"
else
  portal_step control_plane.tenants FAIL "tenants listed: $tenants_seen"
fi

user_count="$(jq '.users | length' "$PORTAL_PLAN")"
users_ok=1
for i in $(seq 0 $((user_count - 1))); do
  alias="$(jq -r ".users[$i].alias" "$PORTAL_PLAN")"
  portal_py secret --bytes 24 >"$PORTAL_PRIV/pw.$alias"
  chmod 600 "$PORTAL_PRIV/pw.$alias"
  python3 - "$PORTAL_PLAN" "$i" "$PORTAL_PRIV/pw.$alias" >"$PORTAL_PRIV/user.$alias.json" <<'PY'
import json, sys
from pathlib import Path
plan = json.loads(Path(sys.argv[1]).read_text())
u = plan["users"][int(sys.argv[2])]
print(json.dumps({"username": u["username"], "role": u["role"], "tenant_ids": u["tenant_ids"],
                  "password": Path(sys.argv[3]).read_text()}))
PY
  portal_api admin PUT /api/admin/users "$PORTAL_PRIV/user.$alias.json" >/dev/null
  rm -f "$PORTAL_PRIV/user.$alias.json"
  [[ "$(portal_last_status)" == "200" ]] || { users_ok=0; echo "user $alias upsert → $(portal_last_status)" >&2; }
done
if (( users_ok )); then
  portal_step control_plane.users PASS "viewer + operator per tenant via /api/admin/users"
else
  portal_step control_plane.users FAIL "user upsert failed"
fi

jq -c '.tenant_admin_probe | {username, role, tenant_ids, password: "qa-rejected-placeholder-0000"}' \
  "$PORTAL_PLAN" >"$PORTAL_PRIV/tenant_admin.json"
portal_api admin PUT /api/admin/users "$PORTAL_PRIV/tenant_admin.json" >"$ART/tenant_admin_probe.json"
if [[ "$(portal_last_status)" == "400" ]]; then
  portal_step control_plane.tenant_admin_rejected PASS "file users cannot be admin; admin identity is the env hub admin"
else
  portal_step control_plane.tenant_admin_rejected FAIL "tenant admin upsert → $(portal_last_status)"
fi

identity_ok=1
for i in $(seq 0 $((user_count - 1))); do
  alias="$(jq -r ".users[$i].alias" "$PORTAL_PLAN")"
  username="$(jq -r ".users[$i].username" "$PORTAL_PLAN")"
  want_role="$(jq -r ".users[$i].role" "$PORTAL_PLAN")"
  want_tenant="$(jq -r ".users[$i].tenant_ids[0]" "$PORTAL_PLAN")"
  if ! portal_login "$alias" "$username"; then
    identity_ok=0
    echo "login $alias failed" >&2
    continue
  fi
  me="$(portal_api "$alias" GET /api/auth/me)"
  if ! jq -e --arg r "$want_role" --arg t "$want_tenant" \
      '(.role | ascii_downcase) == $r and ((.tenant_ids // []) | index($t) != null)' <<<"$me" >/dev/null; then
    identity_ok=0
    echo "identity mismatch for $alias" >&2
  fi
done
if (( identity_ok )); then
  portal_step control_plane.identities PASS "each user logs in with its role and single tenant"
else
  portal_step control_plane.identities FAIL "login or /api/auth/me mismatch"
fi

echo "== Seed one canary package per tenant (operator imports) =="
for side in a b; do
  site="$(jq -r ".tenants.$side.site" "$PORTAL_PLAN")"
  equip="$(jq -r ".tenants.$side.canary_equipment" "$PORTAL_PLAN")"
  portal_py package --building "$site" --equipment "$equip" --rows 48 --out "$ART/package_$side.zip"
  portal_api "operator_$side" POST /api/csv/import/package "$ART/package_$side.zip" application/zip \
    >"$ART/import_$side.json"
  if [[ "$(portal_last_status)" == "200" ]] && jq -e '.ok == true' "$ART/import_$side.json" >/dev/null; then
    portal_step "seed.import_$side" PASS "$site/$equip"
  else
    portal_step "seed.import_$side" FAIL "import → $(portal_last_status)"
  fi
done
for site in "$SITE_A" "$SITE_B"; do
  if n="$(portal_wait_rows "$site" 120)"; then
    portal_step "seed.timescale_rows.$site" PASS "$n rows"
  else
    portal_step "seed.timescale_rows.$site" FAIL "no Timescale samples after import"
  fi
done

echo "== NF emulator ingest (loopback only) =="
if n="$(portal_wait_rows "$NF_SITE" 180)"; then
  portal_step nf.emulator_ingest PASS "$n samples for $NF_SITE"
else
  portal_step nf.emulator_ingest FAIL "no NF emulator samples for $NF_SITE"
fi
portal_compose logs --no-color nf-emulator >"$ART/nf_emulator.log" 2>&1 || true
nf_reads="$(grep -c '"event": "nf_emulator_request"' "$ART/nf_emulator.log" || true)"
nf_writes="$(grep -c '"event": "forbidden_write"' "$ART/nf_emulator.log" || true)"
if [[ "${nf_reads:-0}" -gt 0 && "${nf_writes:-0}" -eq 0 ]]; then
  portal_step deployment.egress.nf_emulator_only PASS "$nf_reads emulator reads, 0 point writes; central has no internet route"
else
  portal_step deployment.egress.nf_emulator_only FAIL "reads=${nf_reads:-0} writes=${nf_writes:-0}"
fi
portal_api operator_a GET /api/providers/sites >"$ART/providers_sites_a.json"
a_status="$(portal_last_status)"
portal_api operator_b GET /api/providers/sites >"$ART/providers_sites_b.json"
b_status="$(portal_last_status)"
if [[ "$a_status" == "200" ]] && grep -q "$NF_SITE" "$ART/providers_sites_a.json" \
    && ! grep -q "$NF_SITE" "$ART/providers_sites_b.json" && [[ "$b_status" =~ ^(200|403)$ ]]; then
  portal_step nf.provider_tenant_scope PASS "tenant A sees $NF_SITE; tenant B does not ($b_status)"
else
  portal_step nf.provider_tenant_scope FAIL "A=$a_status B=$b_status"
fi

echo "== Multi-tenant flag observed =="
mt="$(portal_compose exec -T central printenv OPENFDD_MULTI_TENANT 2>/dev/null || true)"
open_bind="$(portal_compose exec -T central printenv OPENFDD_ALLOW_OPEN_BIND 2>/dev/null || true)"
if [[ "$mt" == "1" && -z "$open_bind" ]]; then
  portal_step deployment.auth.multi_tenant PASS "OPENFDD_MULTI_TENANT=1, no open-bind escape hatch"
else
  portal_step deployment.auth.multi_tenant FAIL "MULTI_TENANT=$mt ALLOW_OPEN_BIND=${open_bind:+set}"
fi

echo "== Timescale fingerprint before the security harness =="
fp_a_before="$(portal_site_fingerprint "$SITE_A")"
fp_b_before="$(portal_site_fingerprint "$SITE_B")"
echo "$SITE_A $fp_a_before" | tee "$ART/fingerprint_before.txt"
echo "$SITE_B $fp_b_before" | tee -a "$ART/fingerprint_before.txt"

echo "== Security harness (isolated_full X Y Z) =="
portal_py probe-config --plan "$PORTAL_PLAN" --base-url "$PORTAL_BASE" --out "$ART/probe_config.json"
set +e
(
  export QA_ADMIN_USER=admin
  QA_ADMIN_PASSWORD="$(cat "$PORTAL_PRIV/pw.admin")"
  export QA_ADMIN_PASSWORD
  for i in $(seq 0 $((user_count - 1))); do
    alias="$(jq -r ".users[$i].alias" "$PORTAL_PLAN")"
    uenv="$(jq -r ".users[$i].username_env" "$PORTAL_PLAN")"
    penv="$(jq -r ".users[$i].password_env" "$PORTAL_PLAN")"
    export "$uenv=$(jq -r ".users[$i].username" "$PORTAL_PLAN")"
    export "$penv=$(cat "$PORTAL_PRIV/pw.$alias")"
  done
  QA_ISOLATED_JWT_SECRET="$(cat "$PORTAL_PRIV/jwt.secret")"
  export QA_ISOLATED_JWT_SECRET
  python3 -B "$ROOT/scripts/security/openfdd_security_probe.py" \
    --config "$ART/probe_config.json" \
    --base-url "$PORTAL_BASE" \
    --profile isolated_full \
    --execute --allow-fixture-writes \
    --isolated-jwt-secret-env QA_ISOLATED_JWT_SECRET \
    --rate 10 --deadline 300 \
    --output-dir "$ART/security"
)
PROBE_RC=$?
set -e
probe_status="$(jq -r '.overall_status // "MISSING"' "$ART/security/security_report.json" 2>/dev/null || echo MISSING)"
probe_bad="$(jq -r '[.checks[] | select(.status == "FAIL" or .status == "ERROR")] | length' \
  "$ART/security/security_report.json" 2>/dev/null || echo unknown)"
if [[ "$PROBE_RC" -eq 0 && "$probe_status" == "PASS" ]]; then
  portal_step security.harness PASS "isolated_full X/Y/Z overall PASS"
elif [[ "$probe_status" == "BLOCKED" && "$probe_bad" == "0" ]]; then
  probe_blocked="$(jq -r '[.checks[] | select(.status == "BLOCKED") | .check_id] | join(" ")' \
    "$ART/security/security_report.json")"
  portal_step security.harness BLOCKED "no FAIL/ERROR; unverified: $probe_blocked"
else
  portal_step security.harness FAIL "rc=$PROBE_RC overall_status=$probe_status"
fi
viewer_matrix="$(jq -r '[.checks[] | select(.check_id | startswith("y.authz.viewer_")) | "\(.check_id)=\(.status)"] | join(" ")' \
  "$ART/security/security_report.json" 2>/dev/null || true)"
if [[ -n "$viewer_matrix" && "$viewer_matrix" != *"=FAIL"* && "$viewer_matrix" != *"=ERROR"* && "$viewer_matrix" != *"=BLOCKED"* ]]; then
  portal_step security.viewer_write_matrix PASS "$viewer_matrix"
else
  portal_step security.viewer_write_matrix FAIL "${viewer_matrix:-no viewer checks in report}"
fi

echo "== Timescale fingerprint after the security harness =="
fp_a_after="$(portal_site_fingerprint "$SITE_A")"
fp_b_after="$(portal_site_fingerprint "$SITE_B")"
echo "$SITE_A $fp_a_after" | tee "$ART/fingerprint_after.txt"
echo "$SITE_B $fp_b_after" | tee -a "$ART/fingerprint_after.txt"
if [[ "$fp_a_before" == "$fp_a_after" && "$fp_b_before" == "$fp_b_after" ]]; then
  portal_step security.no_historian_side_effect PASS "both tenants' sample count + md5 unchanged"
else
  portal_step security.no_historian_side_effect FAIL "historian rows changed during denied writes"
fi

for f in "$ART"/*.json "$ART"/*.log "$ART"/security/*; do
  [[ -f "$f" ]] && portal_redact_file "$f"
done

set +e
portal_py verdict --steps "$PORTAL_STEPS" --suite portal_qualification_v1 \
  --image-tag "$PORTAL_TAG" --out "$ART/verdict.json" --required \
  stack.healthy deployment.services.required deployment.cloud.zero_ot deployment.images.immutable \
  deployment.exposure.private_central_timescale deployment.auth.jwt_required deployment.auth.multi_tenant \
  deployment.egress.nf_emulator_only control_plane.tenants control_plane.users \
  control_plane.tenant_admin_rejected control_plane.identities seed.import_a seed.import_b \
  "seed.timescale_rows.$SITE_A" "seed.timescale_rows.$SITE_B" nf.emulator_ingest nf.provider_tenant_scope \
  security.harness security.viewer_write_matrix security.no_historian_side_effect
VERDICT_RC=$?
set -e
if [[ "$VERDICT_RC" -eq 2 ]]; then
  echo "BLOCKED: portal qualification (no failures; some checks unverified) → $ART/verdict.json" >&2
  exit 2
fi
if [[ "$VERDICT_RC" -ne 0 ]]; then
  echo "FAIL: portal qualification → $ART/verdict.json" >&2
  exit 1
fi
echo "PASS: portal qualification → $ART/verdict.json"
