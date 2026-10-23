#!/usr/bin/env bash
# Backup → empty disposable volumes → restore, on the portal stack
# (deployment profile `cloud_portal`: central + web + Timescale from GHCR).
#
# Proves that the Timescale historian came back (per-site row count + md5 of a
# known fixture site's samples, plus the total sample count) and that the
# workspace / control-plane identity state came back (file manifest, admin API
# tenant + user records, control-plane files with server-minted user ids and
# session epochs, and a login with the original operator password). Then runs a tiny bounded
# API timing check.
#
# Never touches Railway, a live /workspace, or a real site. Teardown and the
# "wipe" step are project-scoped (lib/portal_stack.sh); no `down -v`, no prune.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
# shellcheck source-path=SCRIPTDIR source=lib/portal_stack.sh
source "$ROOT/scripts/qualification/lib/portal_stack.sh"

portal_require_tag
portal_preflight

ART="${ARTIFACT_DIR:-$ROOT/reports/restore_empty_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$ART"
chmod 700 "$ART"
ART="$(cd "$ART" && pwd)"

portal_stack_init restore
trap portal_stack_cleanup EXIT
# Backups hold the control-plane users file; keep them in the private dir.
BK="$PORTAL_PRIV/backup"
mkdir -p "$BK"
chmod 700 "$BK"

SITE="$(jq -r '.tenants.a.site' "$PORTAL_PLAN")"
EQUIP="$(jq -r '.tenants.a.canary_equipment' "$PORTAL_PLAN")"
OP_ALIAS="operator_a"
OP_USER="$(jq -r --arg a "$OP_ALIAS" '.users[] | select(.alias == $a) | .username' "$PORTAL_PLAN")"
WS_VOL="$(portal_volume_name qual-workspace)"
echo "== Restore-to-empty $PORTAL_PREFIX (project $PORTAL_PROJECT, tag $PORTAL_TAG) =="

echo "== Seed: stack, tenant, operator, fixture package =="
portal_stack_up 240
portal_login admin admin || portal_die "admin login failed"
jq -c '.tenants.a | {id, name, building_ids}' "$PORTAL_PLAN" >"$PORTAL_PRIV/tenant.json"
portal_api admin PUT /api/admin/tenants "$PORTAL_PRIV/tenant.json" >/dev/null
[[ "$(portal_last_status)" == "200" ]] || portal_die "tenant upsert → $(portal_last_status)"
portal_py secret --bytes 24 >"$PORTAL_PRIV/pw.$OP_ALIAS"
chmod 600 "$PORTAL_PRIV/pw.$OP_ALIAS"
python3 - "$PORTAL_PLAN" "$OP_ALIAS" "$PORTAL_PRIV/pw.$OP_ALIAS" >"$PORTAL_PRIV/user.json" <<'PY'
import json, sys
from pathlib import Path
plan = json.loads(Path(sys.argv[1]).read_text())
u = next(u for u in plan["users"] if u["alias"] == sys.argv[2])
print(json.dumps({"username": u["username"], "role": u["role"], "tenant_ids": u["tenant_ids"],
                  "password": Path(sys.argv[3]).read_text()}))
PY
portal_api admin PUT /api/admin/users "$PORTAL_PRIV/user.json" >/dev/null
rm -f "$PORTAL_PRIV/user.json"
[[ "$(portal_last_status)" == "200" ]] || portal_die "operator upsert → $(portal_last_status)"
portal_login "$OP_ALIAS" "$OP_USER" || portal_die "operator login failed"
portal_py package --building "$SITE" --equipment "$EQUIP" --rows 96 --out "$ART/fixture_package.zip"
portal_api "$OP_ALIAS" POST /api/csv/import/package "$ART/fixture_package.zip" application/zip >"$ART/import.json"
[[ "$(portal_last_status)" == "200" ]] || portal_die "fixture import → $(portal_last_status)"
rows="$(portal_wait_rows "$SITE" 120)" || portal_die "no Timescale samples for $SITE after import"
portal_step seed.fixture PASS "$SITE/$EQUIP $rows samples"

# identity_state <out-prefix>: admin API tenants/users (sorted) as sha256.
identity_state() {
  portal_login admin admin || portal_die "admin login failed"
  portal_api admin GET /api/admin/tenants | jq -S '.tenants | sort_by(.id)' >"$1.tenants.json"
  [[ "$(portal_last_status)" == "200" ]] || portal_die "admin tenants → $(portal_last_status)"
  portal_api admin GET /api/admin/users | jq -S '.users | sort_by(.username)' >"$1.users.json"
  [[ "$(portal_last_status)" == "200" ]] || portal_die "admin users → $(portal_last_status)"
  printf '%s %s\n' \
    "$(sha256sum <"$1.tenants.json" | cut -d' ' -f1)" \
    "$(sha256sum <"$1.users.json" | cut -d' ' -f1)"
}

# workspace_manifest: sorted "sha256  path" for every file in the workspace volume.
workspace_manifest() {
  # shellcheck disable=SC2016  # expanded by the container shell
  portal_volume_run "$WS_VOL" ro sh -c \
    'cd /w && find . -type f | LC_ALL=C sort | while IFS= read -r f; do sha256sum "$f"; done'
}

control_plane_hashes() {
  # shellcheck disable=SC2016  # expanded by the container shell
  portal_volume_run "$WS_VOL" ro sh -c \
    'cd /w/openfdd/control_plane && for f in tenants.json users.json; do test -s "$f" && sha256sum "$f"; done'
}

echo "== Record pre-backup state =="
FP_BEFORE="$(portal_site_fingerprint "$SITE")"
TOTAL_BEFORE="$(portal_psql "SELECT count(*) FROM sample")"
ID_BEFORE="$(identity_state "$ART/identity_before")"
portal_compose stop central web >/dev/null
MANIFEST_BEFORE="$(workspace_manifest)"
CP_BEFORE="$(control_plane_hashes)"
[[ -n "$CP_BEFORE" ]] || portal_die "control plane files missing before backup"
printf '%s\n' "$MANIFEST_BEFORE" >"$ART/workspace_manifest_before.txt"
jq -n --arg fp "$FP_BEFORE" --arg total "$TOTAL_BEFORE" --arg id "$ID_BEFORE" --arg site "$SITE" \
  '{site: $site, site_count_md5: $fp, total_samples: $total, identity_sha256: $id}' \
  | tee "$ART/state_before.json"

echo "== Backup: pg_dump (custom format) + workspace tarball =="
portal_compose exec -T timescale pg_dump -U openfdd -d openfdd -Fc >"$BK/historian.dump"
test -s "$BK/historian.dump" || portal_die "empty pg_dump"
portal_volume_run "$WS_VOL" ro tar -C /w --numeric-owner -czf - . >"$BK/workspace.tgz"
test -s "$BK/workspace.tgz" || portal_die "empty workspace tarball"
{
  printf 'historian.dump %s bytes sha256=%s\n' "$(wc -c <"$BK/historian.dump")" "$(sha256sum <"$BK/historian.dump" | cut -d' ' -f1)"
  printf 'workspace.tgz %s bytes sha256=%s\n' "$(wc -c <"$BK/workspace.tgz")" "$(sha256sum <"$BK/workspace.tgz" | cut -d' ' -f1)"
} | tee "$ART/backup_sizes.txt"
portal_step backup.created PASS "pg_dump -Fc + workspace tarball"

echo "== Wipe: remove this project's containers and volumes =="
portal_remove_project_volumes
left="$(portal_project_volumes | tr '\n' ' ')"
[[ -z "${left// /}" ]] || portal_die "project volumes survived wipe: $left"
portal_step wipe.empty PASS "no volumes labelled $PORTAL_PROJECT remain"

echo "== Restore Timescale onto a fresh volume =="
portal_compose up -d --no-build timescale >/dev/null
portal_wait_timescale 180
fresh_count="$(portal_psql "SELECT count(*) FROM sample" 2>/dev/null || echo 0)"
[[ "$fresh_count" == "0" ]] || portal_die "fresh Timescale volume is not empty ($fresh_count samples)"
PORTAL_PSQL_DB=postgres portal_psql "DROP DATABASE openfdd WITH (FORCE)" >/dev/null
PORTAL_PSQL_DB=postgres portal_psql "CREATE DATABASE openfdd" >/dev/null
portal_psql "CREATE EXTENSION IF NOT EXISTS timescaledb" >/dev/null
portal_psql "SELECT timescaledb_pre_restore()" >/dev/null
set +e
portal_compose exec -T timescale pg_restore -U openfdd -d openfdd --no-owner <"$BK/historian.dump" \
  >"$ART/pg_restore.log" 2>&1
RESTORE_RC=$?
set -e
portal_psql "SELECT timescaledb_post_restore()" >/dev/null
# pg_restore warns on the pre-created extension; the fingerprints below decide.
echo "pg_restore rc=$RESTORE_RC (see pg_restore.log)"

echo "== Restore workspace onto a fresh volume =="
portal_compose up --no-start --no-build central web >/dev/null
ws_files="$(portal_volume_run "$WS_VOL" ro sh -c 'find /w -type f | wc -l' | tr -d ' ')"
[[ "$ws_files" == "0" ]] || portal_die "fresh workspace volume is not empty ($ws_files files)"
portal_volume_run "$WS_VOL" rw tar -C /w --numeric-owner -xzpf - <"$BK/workspace.tgz"
MANIFEST_AFTER="$(workspace_manifest)"
printf '%s\n' "$MANIFEST_AFTER" >"$ART/workspace_manifest_after.txt"
if [[ "$MANIFEST_BEFORE" == "$MANIFEST_AFTER" ]]; then
  portal_step restore.workspace_manifest PASS "$(wc -l <<<"$MANIFEST_AFTER" | tr -d ' ') files, sha256 identical"
else
  portal_step restore.workspace_manifest FAIL "workspace file manifest differs"
fi

echo "== Boot central + web on the restored state =="
portal_compose up -d --no-build >/dev/null
portal_wait_health 240

FP_AFTER="$(portal_site_fingerprint "$SITE")"
TOTAL_AFTER="$(portal_psql "SELECT count(*) FROM sample")"
if [[ "$FP_AFTER" == "$FP_BEFORE" && "${FP_AFTER%%:*}" -gt 0 ]]; then
  portal_step restore.timescale_fixture_site PASS "$SITE count:md5 $FP_AFTER matches pre-backup"
else
  portal_step restore.timescale_fixture_site FAIL "before=$FP_BEFORE after=$FP_AFTER"
fi
if [[ "$TOTAL_AFTER" == "$TOTAL_BEFORE" ]]; then
  portal_step restore.timescale_total PASS "$TOTAL_AFTER samples"
else
  portal_step restore.timescale_total FAIL "before=$TOTAL_BEFORE after=$TOTAL_AFTER"
fi

ID_AFTER="$(identity_state "$ART/identity_after")"
if [[ "$ID_AFTER" == "$ID_BEFORE" ]]; then
  portal_step restore.control_plane_api PASS "tenants + users (roles, memberships, disabled) identical"
else
  portal_step restore.control_plane_api FAIL "admin API identity state differs"
fi
CP_AFTER="$(control_plane_hashes)"
if [[ "$CP_AFTER" == "$CP_BEFORE" ]]; then
  portal_step restore.control_plane_files PASS "tenants.json + users.json (user ids, session epochs) sha256 identical after boot"
else
  portal_step restore.control_plane_files FAIL "control-plane files changed after boot"
fi
rm -f "$PORTAL_PRIV/hdr.$OP_ALIAS" "$PORTAL_PRIV/tok.$OP_ALIAS"
if portal_login "$OP_ALIAS" "$OP_USER" \
    && portal_api "$OP_ALIAS" GET /api/auth/me \
      | jq -e --arg t "$(jq -r '.tenants.a.id' "$PORTAL_PLAN")" '(.tenant_ids // []) | index($t) != null' >/dev/null; then
  portal_step restore.operator_login PASS "original operator password + tenant membership work"
else
  portal_step restore.operator_login FAIL "restored operator cannot log in or lost its tenant"
fi
ds="$(portal_api "$OP_ALIAS" GET "/api/datasets?building_id=$SITE")"
if [[ "$(portal_last_status)" == "200" ]] && jq -e --arg s "$SITE" '[.datasets[]? | (.id // .building_id)] | index($s) != null' <<<"$ds" >/dev/null; then
  portal_step restore.dataset_visible PASS "$SITE listed for its operator"
else
  portal_step restore.dataset_visible FAIL "datasets → $(portal_last_status)"
fi

echo "== Bounded API timings =="
BASELINE="$ROOT/scripts/qualification/fixtures/bounded_perf_baseline.json"
TIMINGS="$ART/bounded_perf_timings.jsonl"
: >"$TIMINGS"
portal_login admin admin || portal_die "admin login failed"
measure() {
  local path="$1" _ start end
  for _ in $(seq 1 20); do
    start="$(date +%s%N)"
    curl -fsS --max-time 5 -H "@$PORTAL_PRIV/hdr.admin" "$PORTAL_BASE$path" >/dev/null
    end="$(date +%s%N)"
    echo "{\"path\":\"${path}\",\"ms\":$(( (end - start) / 1000000 ))}" >>"$TIMINGS"
  done
}
curl -fsS "$PORTAL_BASE/api/health" >/dev/null
measure /api/health
measure /api/datasets

set +e
python3 - "$TIMINGS" "$BASELINE" "$ART/bounded_perf_verdict.json" <<'PY'
import json, sys
from pathlib import Path
timings_path, baseline_path, out_path = sys.argv[1:4]
rows = [json.loads(l) for l in Path(timings_path).read_text().splitlines() if l.strip()]
by = {}
for r in rows:
    by.setdefault(r["path"], []).append(r["ms"])
def pct(xs, p):
    xs = sorted(xs)
    return xs[int(round((p / 100) * (len(xs) - 1)))] if xs else None
summary = {p: {"n": len(xs), "p50_ms": pct(xs, 50), "p95_ms": pct(xs, 95), "max_ms": max(xs)} for p, xs in by.items()}
baseline = json.loads(Path(baseline_path).read_text())
ok, checks = True, {}
for path, budget in baseline.get("budgets_ms", {}).items():
    got = summary.get(path)
    if not got:
        checks[path] = {"ok": False, "reason": "missing"}
        ok = False
        continue
    good = got["p50_ms"] <= budget["p50"] and got["p95_ms"] <= budget["p95"]
    checks[path] = {"ok": good, "got": got, "budget": budget}
    ok = ok and good
Path(out_path).write_text(json.dumps({"suite": "bounded_perf_v1", "pass": ok, "summary": summary, "checks": checks}, indent=2) + "\n")
sys.exit(0 if ok else 1)
PY
PERF_RC=$?
set -e
if [[ "$PERF_RC" -eq 0 ]]; then
  portal_step perf.bounded PASS "within bounded_perf_baseline.json"
else
  portal_step perf.bounded FAIL "see bounded_perf_verdict.json"
fi

for f in "$ART"/*.json "$ART"/*.log "$ART"/*.txt; do
  [[ -f "$f" ]] && portal_redact_file "$f"
done

set +e
portal_py verdict --steps "$PORTAL_STEPS" --suite restore_to_empty_v2 \
  --image-tag "$PORTAL_TAG" --out "$ART/verdict.json" --required \
  seed.fixture backup.created wipe.empty restore.workspace_manifest restore.timescale_fixture_site \
  restore.timescale_total restore.control_plane_api restore.control_plane_files restore.operator_login \
  restore.dataset_visible perf.bounded
VERDICT_RC=$?
set -e
if [[ "$VERDICT_RC" -ne 0 ]]; then
  echo "FAIL: restore-to-empty → $ART/verdict.json" >&2
  exit 1
fi
echo "PASS: restore-to-empty → $ART/verdict.json"
