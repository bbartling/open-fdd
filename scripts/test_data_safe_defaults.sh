#!/usr/bin/env bash
# Defaults never prune volumes, reset workspace scratch, or reload an occupied Timescale.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck source=scripts/openfdd_data_safety.sh
source "$ROOT/scripts/openfdd_data_safety.sh"

unset OPENFDD_ALLOW_DESTRUCTIVE_DB || true

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

echo "== volume and compose guards =="
openfdd_reject_destructive_compose_args central web
if openfdd_reject_destructive_compose_args down; then
  fail "down was accepted without opt-in"
fi
if openfdd_reject_destructive_compose_args -v; then
  fail "-v was accepted without opt-in"
fi
if openfdd_reject_destructive_compose_args --volumes; then
  fail "--volumes was accepted without opt-in"
fi
if openfdd_reject_destructive_compose_args --renew-anon-volumes; then
  fail "--renew-anon-volumes was accepted without opt-in"
fi
if openfdd_allow_volume_delete "openfdd-timescale"; then
  fail "product timescale volume delete was accepted"
fi
if openfdd_allow_volume_delete "openfdd-portal_openfdd-timescale"; then
  fail "compose project timescale volume delete was accepted"
fi
if openfdd_allow_volume_delete "openfdd-wavex-ts_openfdd-timescale"; then
  fail "wavex timescale volume delete was accepted"
fi
if openfdd_allow_volume_delete "some-operator-volume"; then
  fail "unnamed volume delete was accepted"
fi
openfdd_allow_volume_delete "openfdd-csv-smoke-99"
openfdd_allow_volume_delete "openfdd-restore-empty-7-workspace"
openfdd_allow_volume_delete "openfdd-bacnet-mqtt-ci-1-2"
openfdd_allow_volume_delete "openfdd-zap-central-3-workspace"
OPENFDD_ALLOW_DESTRUCTIVE_DB=1 openfdd_reject_destructive_compose_args --volumes
OPENFDD_ALLOW_DESTRUCTIVE_DB=1 openfdd_allow_volume_delete "openfdd-timescale"
unset OPENFDD_ALLOW_DESTRUCTIVE_DB

echo "== update scripts do not prune or drop by default =="
if grep -nE 'volume prune|down -v|down --volumes' \
  scripts/openfdd_stack_up.sh \
  scripts/openfdd_maint_update_resume.sh \
  scripts/railway_repin_hub.sh \
  scripts/openfdd_railway_release.sh; then
  fail "update/re-pin script contains an unguarded volume wipe"
fi
if grep -n 'railway volume delete' scripts/railway_repin_hub.sh scripts/openfdd_railway_release.sh; then
  fail "re-pin script deletes Railway volumes"
fi
if grep -n 'setdefault("OPENFDD_SEED_FORCE"' scripts/timescale/package_to_timescale.py; then
  fail "package_to_timescale forces a reload by default"
fi

echo "== docker maintenance keeps volumes unless opted in =="
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
DOCKER_LOG="$TMP/docker.log"
export DOCKER_LOG
mkdir -p "$TMP/bin"
cat >"$TMP/bin/docker" <<'EOF'
#!/bin/sh
printf '%s\n' "$*" >>"${DOCKER_LOG:?}"
exit 0
EOF
chmod +x "$TMP/bin/docker"

run_maint() {
  : >"$DOCKER_LOG"
  PATH="$TMP/bin:$PATH" ./scripts/openfdd_docker_maintenance.sh "$@"
}

run_maint
if grep -q 'volume prune' "$DOCKER_LOG"; then
  fail "default maintenance pruned volumes"
fi

set +e
default_refuse="$(PATH="$TMP/bin:$PATH" ./scripts/openfdd_docker_maintenance.sh --prune-volumes 2>&1)"
refuse_code=$?
set -e
[[ "$refuse_code" -eq 1 ]] || fail "prune-volumes without opt-in exited $refuse_code"
printf '%s\n' "$default_refuse" | grep -q 'REFUSED' || fail "prune-volumes did not refuse"
if grep -q 'volume prune' "$DOCKER_LOG"; then
  fail "refused prune still invoked docker volume prune"
fi

set +e
half="$(PATH="$TMP/bin:$PATH" ./scripts/openfdd_docker_maintenance.sh --prune-volumes --i-understand-data-loss 2>&1)"
half_code=$?
set -e
[[ "$half_code" -eq 1 ]] || fail "partial opt-in exited $half_code"
printf '%s\n' "$half" | grep -q 'REFUSED' || fail "partial opt-in did not refuse"

: >"$DOCKER_LOG"
PATH="$TMP/bin:$PATH" ./scripts/openfdd_docker_maintenance.sh \
  --prune-volumes --reset-db --i-understand-data-loss >/dev/null
grep -q 'volume prune' "$DOCKER_LOG" || fail "explicit flags did not prune volumes"

: >"$DOCKER_LOG"
OPENFDD_ALLOW_DESTRUCTIVE_DB=1 PATH="$TMP/bin:$PATH" \
  ./scripts/openfdd_docker_maintenance.sh --prune-volumes >/dev/null
grep -q 'volume prune' "$DOCKER_LOG" || fail "env opt-in did not prune volumes"
unset OPENFDD_ALLOW_DESTRUCTIVE_DB

: >"$DOCKER_LOG"
OPENFDD_ALLOW_DESTRUCTIVE_DB=1 PATH="$TMP/bin:$PATH" \
  ./scripts/openfdd_docker_maintenance.sh >/dev/null
if grep -q 'volume prune' "$DOCKER_LOG"; then
  fail "env alone pruned volumes without --prune-volumes"
fi
unset OPENFDD_ALLOW_DESTRUCTIVE_DB

echo "== workspace reset refuses by default =="
set +e
reset_out="$(./scripts/openfdd_workspace_reset_default.sh 2>&1)"
reset_code=$?
set -e
[[ "$reset_code" -eq 2 ]] || fail "workspace reset default exited $reset_code"
printf '%s\n' "$reset_out" | grep -q 'REFUSED' || fail "workspace reset default did not refuse"

set +e
reset_opt="$(OPENFDD_WORKSPACE="$TMP/missing-workspace" \
  ./scripts/openfdd_workspace_reset_default.sh --reset-db --i-understand-data-loss 2>&1)"
reset_opt_code=$?
set -e
[[ "$reset_opt_code" -eq 1 ]] || fail "opt-in workspace reset exited $reset_opt_code"
printf '%s\n' "$reset_opt" | grep -q 'WARNING: DATA LOSS' || fail "opt-in reset was silent"
printf '%s\n' "$reset_opt" | grep -q 'workspace not found' || fail "opt-in reset did not reach the workspace check"

set +e
env_reset="$(OPENFDD_ALLOW_DESTRUCTIVE_DB=1 OPENFDD_WORKSPACE="$TMP/missing-workspace-env" \
  ./scripts/openfdd_workspace_reset_default.sh 2>&1)"
env_reset_code=$?
set -e
[[ "$env_reset_code" -eq 1 ]] || fail "env opt-in workspace reset exited $env_reset_code"
printf '%s\n' "$env_reset" | grep -q 'WARNING: DATA LOSS' || fail "env opt-in reset was silent"
unset OPENFDD_ALLOW_DESTRUCTIVE_DB

echo "== lab seed decision =="
python3 - <<'PY'
import sys
sys.path.insert(0, "scripts/timescale")
from seed_safety import decide_seed

def check(expected, **kwargs):
    got = decide_seed(**kwargs)
    if got != expected:
        raise SystemExit(f"decide_seed {kwargs} -> {got}, want {expected}")

check("proceed_empty", marker_ok=False, existing_samples=0, existing_sites=0, env={})
check("refuse", marker_ok=False, existing_samples=1, existing_sites=0, env={})
check("refuse", marker_ok=False, existing_samples=0, existing_sites=1, env={})
check("skip_already", marker_ok=True, existing_samples=4, existing_sites=1, env={})
check("refuse", marker_ok=False, existing_samples=2, existing_sites=1, env={"OPENFDD_SEED_FORCE": "1"})
check("refuse", marker_ok=False, existing_samples=2, existing_sites=1, env={"OPENFDD_ALLOW_DESTRUCTIVE_DB": "1"})
check("refuse", marker_ok=True, existing_samples=2, existing_sites=1, env={"OPENFDD_SEED_FORCE": "1"})
check(
    "reload",
    marker_ok=False,
    existing_samples=2,
    existing_sites=1,
    env={"OPENFDD_SEED_FORCE": "1", "OPENFDD_ALLOW_DESTRUCTIVE_DB": "1"},
)
check(
    "reload",
    marker_ok=True,
    existing_samples=2,
    existing_sites=1,
    env={"OPENFDD_SEED_FORCE": "true", "OPENFDD_ALLOW_DESTRUCTIVE_DB": "yes"},
)
check(
    "proceed_empty",
    marker_ok=False,
    existing_samples=0,
    existing_sites=0,
    env={"OPENFDD_SEED_FORCE": "1"},
)
print("seed decisions ok")
PY

echo "PASS data-safe defaults"
