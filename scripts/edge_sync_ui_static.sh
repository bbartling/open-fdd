#!/usr/bin/env bash
# Rsync operator dashboard static bundle to edge workspace bind mount.
#
# Bridge prefers ~/open-fdd/workspace/api/static/app over image-baked assets when
# index.html exists (static_dashboard_dir). Use after build_operator_dashboard.sh
# when GHCR image pull alone leaves a stale hash on disk.
#
#   ./scripts/edge_sync_ui_static.sh --limit acme_vm_bbartling
#   ./scripts/edge_sync_ui_static.sh --host 100.x.x.x --ssh-user bbartling
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

LIMIT=""
HOST=""
SSH_USER="${ANSIBLE_REMOTE_USER:-ben}"
REMOTE_DIR="${OPENFDD_REMOTE_DIR:-~/open-fdd}"
SRC="${ROOT}/workspace/api/static/app/"
DEST_SUFFIX="/workspace/api/static/app/"

usage() {
  sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

load_edge_secrets() {
  local limit="${1:-}"
  local secrets_dir="${ROOT}/infra/ansible/secrets"
  local secrets_file=""
  if [[ -n "$limit" && -f "${secrets_dir}/${limit}.env.local" ]]; then
    secrets_file="${secrets_dir}/${limit}.env.local"
  else
    case "$limit" in
      acme_vm_bbartling) secrets_file="${secrets_dir}/acme.env.local" ;;
      bacnet_pi) secrets_file="${secrets_dir}/bacnet_pi.env.local" ;;
    esac
  fi
  if [[ -n "$secrets_file" && -f "$secrets_file" ]]; then
    set -a
    # shellcheck source=/dev/null
    source "$secrets_file"
    set +a
    export SSHPASS="${SSHPASS:-}"
  fi
}

build_ssh_rsync() {
  RSYNC_SSH=(ssh -o ConnectTimeout=15)
  if [[ -n "${SSHPASS:-}" ]] && command -v sshpass >/dev/null 2>&1; then
    export SSHPASS
    RSYNC_SSH=(sshpass -e ssh -o ConnectTimeout=15 -o PreferredAuthentications=password -o PubkeyAuthentication=no)
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --limit) LIMIT="$2"; shift 2 ;;
    --host) HOST="$2"; shift 2 ;;
    --ssh-user) SSH_USER="$2"; shift 2 ;;
    --remote-dir) REMOTE_DIR="$2"; shift 2 ;;
    -h|--help) usage 0 ;;
    *) echo "Unknown arg: $1" >&2; usage 1 ;;
  esac
done

[[ -f "${SRC}index.html" ]] || {
  echo "Missing ${SRC}index.html — run ./scripts/build_operator_dashboard.sh prod first" >&2
  exit 1
}

INV="${ANSIBLE_INVENTORY:-${ROOT}/infra/ansible/inventory.yml}"
if [[ -n "$LIMIT" ]]; then
  load_edge_secrets "$LIMIT"
  if [[ -z "$HOST" && -f "$INV" ]] && command -v ansible-inventory >/dev/null 2>&1; then
    inv_json="$(ansible-inventory -i "$INV" --host "$LIMIT" 2>/dev/null || true)"
    if [[ -n "$inv_json" ]]; then
      HOST="$(echo "$inv_json" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("ansible_host",""))' 2>/dev/null || true)"
      inv_user="$(echo "$inv_json" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("ansible_user",""))' 2>/dev/null || true)"
      [[ -n "$inv_user" ]] && SSH_USER="$inv_user"
    fi
  fi
fi

[[ -n "$HOST" ]] || { echo "Need --limit <inventory_host> or --host <ip>" >&2; exit 1; }

build_ssh_rsync
REMOTE="${SSH_USER}@${HOST}:${REMOTE_DIR%/}${DEST_SUFFIX}"
echo "==> Rsync UI static bundle → ${REMOTE}"
rsync -az --delete -e "$(printf '%q ' "${RSYNC_SSH[@]}")" "${SRC}" "${REMOTE}"
asset="$(grep -oE 'index-[^"]+\.js' "${SRC}index.html" | head -1 || true)"
echo "OK — edge UI bundle ${asset:-?} synced to ${HOST}"
