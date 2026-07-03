#!/usr/bin/env bash
# Remove bench test artifacts — keeps site config, auth, haystack, commission env.
# Never touches docker volumes or workspace secrets.
#
#   ./scripts/openfdd_bench_cleanup.sh          # dry-run list
#   ./scripts/openfdd_bench_cleanup.sh --apply  # delete
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APPLY=0
[[ "${1:-}" == "--apply" ]] && APPLY=1

log() { echo "[cleanup] $*"; }

stop_test_procs() {
  "$ROOT/scripts/openfdd_bacnet_poll_daemon.sh" stop 2>/dev/null || true
  for pat in openfdd_rigorous_full_run openfdd_hour_driver_fault_test openfdd_patch_cycle_validate \
    openfdd_driver_poll_1m openfdd_soak_pcap openfdd_zap; do
    pkill -f "$pat" 2>/dev/null || true
  done
  rm -f "$ROOT/workspace/logs/"*.pid "$ROOT/workspace/logs/rigorous_full_nohup.pid" 2>/dev/null || true
}

prune_path() {
  local p="$1"
  [[ -e "$p" ]] || return 0
  if [[ "$APPLY" == "1" ]]; then
    if ! rm -rf "$p" 2>/dev/null; then
      log "permission fix via alpine for $p"
      docker run --rm -v "$ROOT/workspace:/ws" alpine sh -c "rm -rf /ws/${p#"$ROOT/workspace/"}" 2>/dev/null \
        || log "WARN: could not remove $p"
    else
      log "removed $p"
    fi
  else
    log "would remove $p"
  fi
}

stop_test_procs

# Test logs and patch zips
prune_path "$ROOT/workspace/logs"
mkdir -p "$ROOT/workspace/logs"

# Empty backup dir on bench (not external HOME backups unless OPENFDD_PURGE_HOME_BACKUPS=1)
prune_path "$ROOT/workspace/backups"
mkdir -p "$ROOT/workspace/backups"

# Old split reports / agent prompts (single report lives in workspace/reports/BENCH_VALIDATION_REPORT.md)
for f in "$ROOT/workspace/reports/FINAL_"*.md "$ROOT/workspace/reports/generated"; do
  prune_path "$f"
done

prune_path "$ROOT/workspace/agent-prompts"

# Stale pointers
rm -f "$ROOT/workspace/logs/patch_latest."* "$ROOT/workspace/logs/rigorous_full_latest.dir" 2>/dev/null || true

if [[ "$APPLY" == "1" ]]; then
  log "done — kept workspace/{data.env.local,auth.env.local,haystack,bacnet,bench,smoke-profiles,data}"
else
  log "dry-run only — re-run with --apply to delete"
fi
