#!/usr/bin/env bash
# Backup live workspace state for one site into edge_backup/local/<site>/<building>/.
#
#   ./scripts/edge_site_backup.sh demo bens-office
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SITE_ID="${1:-demo}"
BUILDING_ID="${2:-bens-office}"

export OPENFDD_REPO_ROOT="$ROOT"
export OPENFDD_WORKSPACE_DIR="${ROOT}/workspace"
export OFDD_DESKTOP_DATA_DIR="${ROOT}/workspace/data"
export PYTHONPATH="${ROOT}/workspace/api"

DEST="$("${ROOT}/.venv/bin/python" <<PY
from openfdd_bridge.site_pack import SitePackRef, backup_site
ref = SitePackRef(site_id="${SITE_ID}", building_id="${BUILDING_ID}")
print(backup_site(ref))
PY
)"
echo "OK — backed up to ${DEST}"
