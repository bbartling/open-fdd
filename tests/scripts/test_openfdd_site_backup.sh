#!/usr/bin/env bash
# openfdd_site_backup.sh — fast mode and timeout env parsing.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT="${ROOT}/scripts/openfdd_site_backup.sh"

[[ -x "$SCRIPT" ]] || { echo "missing $SCRIPT"; exit 1; }

grep -q 'openfdd-backups/latest' "$SCRIPT" || { echo "missing rolling latest backup default"; exit 1; }
grep -q 'BACKUP_INCLUDE_POLL_SAMPLES' "$SCRIPT" || { echo "missing poll sample toggle"; exit 1; }
grep -q 'BACKUP_TIMEOUT_SECS' "$SCRIPT" || { echo "missing backup timeout"; exit 1; }
grep -q 'fix_edge_workspace_permissions' "$SCRIPT" || { echo "missing edge permission fix hook"; exit 1; }

[[ -x "${ROOT}/scripts/upgrade_edge_site.sh" ]] || { echo "missing upgrade_edge_site.sh"; exit 1; }
grep -q 'fast-backup' "${ROOT}/scripts/upgrade_edge_site.sh" || { echo "missing --fast-backup"; exit 1; }

echo "openfdd_site_backup helpers ok"
