#!/usr/bin/env bash
# Defaults for update/maintenance scripts never prune volumes or reset the workspace.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# shellcheck source=scripts/lib/data_safe.sh
source "$ROOT/scripts/lib/data_safe.sh"

[[ "$(openfdd_volume_prune_decision 0 0)" == "skip" ]]
[[ "$(openfdd_volume_prune_decision 0 1)" == "skip" ]]
[[ "$(openfdd_volume_prune_decision 1 0)" == "refuse" ]]
[[ "$(openfdd_volume_prune_decision 1 1)" == "prune" ]]
openfdd_env_flag_on 1
openfdd_env_flag_on true
openfdd_env_flag_on YES
if openfdd_env_flag_on 0; then
  echo "FAIL: 0 must not enable a destructive flag" >&2
  exit 1
fi
if openfdd_env_flag_on ""; then
  echo "FAIL: empty must not enable a destructive flag" >&2
  exit 1
fi

out="$(./scripts/openfdd_docker_maintenance.sh --dry-run)"
grep -q 'data_safe_action=skip' <<<"$out"

set +e
out="$(./scripts/openfdd_docker_maintenance.sh --dry-run --prune-volumes 2>&1)"
code=$?
set -e
[[ "$code" == "2" ]]
grep -q 'data_safe_action=refuse' <<<"$out"
grep -q 'REFUSING' <<<"$out"

out="$(./scripts/openfdd_docker_maintenance.sh --dry-run --prune-volumes --i-understand-data-loss)"
grep -q 'data_safe_action=prune' <<<"$out"

out="$(OPENFDD_ALLOW_DESTRUCTIVE_DB=1 ./scripts/openfdd_docker_maintenance.sh --dry-run --prune-volumes)"
grep -q 'data_safe_action=prune' <<<"$out"

out="$(OPENFDD_ALLOW_DESTRUCTIVE_DB=1 ./scripts/openfdd_docker_maintenance.sh --dry-run)"
grep -q 'data_safe_action=skip' <<<"$out"

set +e
out="$(./scripts/openfdd_workspace_reset_default.sh --dry-run 2>&1)"
code=$?
set -e
[[ "$code" == "2" ]]
grep -q 'REFUSING' <<<"$out"

out="$(./scripts/openfdd_workspace_reset_default.sh --dry-run --i-understand-data-loss)"
grep -q 'data_safe_action=reset_workspace' <<<"$out"

out="$(OPENFDD_ALLOW_DESTRUCTIVE_DB=1 ./scripts/openfdd_workspace_reset_default.sh --dry-run)"
grep -q 'data_safe_action=reset_workspace' <<<"$out"

for path in \
  scripts/openfdd_stack_up.sh \
  scripts/openfdd_maint_update_resume.sh \
  scripts/openfdd_railway_release.sh \
  scripts/railway_repin_hub.sh
do
  if grep -nE 'docker[[:space:]]+volume[[:space:]]+(prune|rm)|compose[[:space:]]+down[[:space:]]+(-v|--volumes)' "$path"; then
    echo "FAIL: $path still destroys volumes on the update path" >&2
    exit 1
  fi
done

echo "OK data-safe update defaults"
