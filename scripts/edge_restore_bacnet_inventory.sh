#!/usr/bin/env bash
# Restore BACnet device-tree inventory on an edge VM after deploy clobbered points_discovered.csv.
#
#   ./scripts/edge_restore_bacnet_inventory.sh acme vm-bbartling
#   ./scripts/edge_restore_bacnet_inventory.sh acme vm-bbartling --host 192.168.204.12
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SITE="${1:?site_id (e.g. acme)}"
BLDG="${2:?building_id (e.g. vm-bbartling)}"
HOST="${EDGE_HOST:-}"
shift 2 || true
while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      if [[ $# -lt 2 || -z "${2:-}" ]]; then
        echo "ERROR: --host requires an IP or hostname" >&2
        exit 1
      fi
      HOST="$2"
      shift 2
      ;;
    *) echo "Unknown: $1" >&2; exit 1 ;;
  esac
done

if [[ "${SSH_STRICT_MODE:-}" == "0" ]]; then
  SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null)
else
  SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new)
fi

PACK="${ROOT}/edge_backup/local/${SITE}/${BLDG}"
DISC="${PACK}/points_discovered.csv"
PTS="${PACK}/points.csv"
[[ -f "$DISC" ]] || { echo "Missing ${DISC} — run: ./scripts/edge_site_backup.sh ${SITE} ${BLDG}" >&2; exit 1; }

if [[ -z "$HOST" ]]; then
  INV="${ROOT}/infra/ansible/inventory.yml"
  if [[ -f "$INV" ]]; then
    HOST="$(python3 - <<PY
import yaml
from pathlib import Path
inv = yaml.safe_load(Path("${INV}").read_text())
for name, h in (inv.get("all", {}).get("hosts") or {}).items():
    if h.get("site_id") == "${SITE}" and h.get("building_id") == "${BLDG}":
        print(h.get("ansible_host", ""))
        break
PY
)"
  fi
fi
[[ -n "$HOST" ]] || { echo "Set EDGE_HOST or pass --host" >&2; exit 1; }

REMOTE="${ANSIBLE_REMOTE_USER:-ben}@${HOST}"
REMOTE_DIR="${OPENFDD_REMOTE_DIR:-/home/ben/open-fdd}"

echo "Copying BACnet inventory to ${REMOTE}..."
scp "${SSH_OPTS[@]}" "$DISC" "${REMOTE}:${REMOTE_DIR}/workspace/bacnet/commissioning/points_discovered.csv"
if [[ -f "$PTS" ]]; then
  scp "${SSH_OPTS[@]}" "$PTS" "${REMOTE}:${REMOTE_DIR}/workspace/bacnet/commissioning/points.csv"
fi

echo "Restarting bridge + commission containers..."
ssh "${SSH_OPTS[@]}" "$REMOTE" "cd ${REMOTE_DIR} && docker compose -f docker/compose.edge.yml restart bridge commission 2>/dev/null || docker compose restart bridge commission"

echo "Done. Open BACnet → Devices & points; tree should list devices. Verify:"
echo "  cd ${ROOT}/infra/ansible && ./scripts/post_deploy_check.sh --host ${HOST}"
