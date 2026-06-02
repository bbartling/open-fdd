#!/usr/bin/env bash
# Apply a site pack (edge_config/ or edge_backup/local/) into workspace — no cross-site bleed.
#
#   ./scripts/edge_site_apply.sh demo bens-office
#   ./scripts/edge_site_apply.sh acme vm-bbartling --from-backup
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SITE_ID="${1:-demo}"
BUILDING_ID="${2:-bens-office}"
FROM_BACKUP=0
shift 2 2>/dev/null || true
while [[ $# -gt 0 ]]; do
  case "$1" in
    --from-backup) FROM_BACKUP=1; shift ;;
    -h|--help)
      sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown: $1" >&2; exit 1 ;;
  esac
done

export OPENFDD_REPO_ROOT="$ROOT"
export OPENFDD_WORKSPACE_DIR="${ROOT}/workspace"
export OFDD_DESKTOP_DATA_DIR="${ROOT}/workspace/data"
export PYTHONPATH="${ROOT}/workspace/api"

PACK_ROOT="${ROOT}/edge_backup/local/${SITE_ID}/${BUILDING_ID}"
if [[ "$FROM_BACKUP" == 0 && -d "${ROOT}/edge_config/${SITE_ID}/${BUILDING_ID}" ]]; then
  PACK_ROOT="${ROOT}/edge_config/${SITE_ID}/${BUILDING_ID}"
fi

"${ROOT}/.venv/bin/python" <<PY
from openfdd_bridge.site_pack import SitePackRef, apply_site
from pathlib import Path

ref = SitePackRef(site_id="${SITE_ID}", building_id="${BUILDING_ID}")
applied = apply_site(ref, pack_root=Path("${PACK_ROOT}"), forbid_acme_rules=${SITE_ID} != "acme")
for k, v in applied.items():
    print(f"  applied {k} -> {v}")
PY

echo "OK — site pack ${SITE_ID}/${BUILDING_ID} applied from ${PACK_ROOT}"
