#!/usr/bin/env bash
# openfdd_site_*.sh — lib helpers, backup/update env contracts.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

LIB="${ROOT}/scripts/openfdd_site_lib.sh"
BACKUP="${ROOT}/scripts/openfdd_site_backup.sh"
UPDATE="${ROOT}/scripts/openfdd_site_update.sh"

for f in "$LIB" "$BACKUP" "$UPDATE"; do
  [[ -f "$f" ]] || { echo "missing $f"; exit 1; }
done

grep -q 'openfdd-backups/latest' "$BACKUP" || { echo "missing rolling latest backup default"; exit 1; }
grep -q 'BACKUP_INCLUDE_POLL_SAMPLES' "$BACKUP" || { echo "missing poll sample toggle"; exit 1; }
grep -q 'openfdd_site_lib.sh' "$UPDATE" || { echo "update must source lib"; exit 1; }
grep -q 'openfdd_safe_docker_maintenance' "$UPDATE" || { echo "missing docker maintenance"; exit 1; }
grep -q 'PURGE_BACKUP_AFTER_SUCCESS' "$UPDATE" || { echo "missing backup purge flag"; exit 1; }
grep -q 'RESTORE_FEATHER_MAX_GIB' "$UPDATE" || { echo "missing feather restore cap"; exit 1; }
grep -q 'openfdd_purge_backup_dir' "$LIB" || { echo "missing purge helper"; exit 1; }
grep -q 'openfdd_apply_feather_restore_cap' "$LIB" || { echo "missing feather cap helper"; exit 1; }

# Feather cap: create fake shards, verify oldest removed.
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
FEATHER="$TMP/feather_store/bacnet/demo"
mkdir -p "$FEATHER"
for i in 1 2 3; do
  dd if=/dev/zero of="$FEATHER/shard-1000${i}-test.feather" bs=1M count=2 status=none
done
# shellcheck source=/dev/null
source "$LIB"
openfdd_apply_feather_restore_cap "$TMP/feather_store" 0
[[ $(find "$TMP/feather_store" -name 'shard-*.feather' | wc -l) -eq 3 ]] || { echo "cap=0 should keep all shards"; exit 1; }
openfdd_apply_feather_restore_cap "$TMP/feather_store" 0.003
remaining=$(find "$TMP/feather_store" -name 'shard-*.feather' | wc -l)
[[ "$remaining" -lt 3 ]] || { echo "cap should drop oldest shards (got $remaining)"; exit 1; }

echo "openfdd_site scripts ok"
