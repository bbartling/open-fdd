#!/usr/bin/env bash
# Acme edge: backup workspace → GHCR image upgrade → prune old backups → health check.
#
#   OPENFDD_IMAGE_TAG=3.1.3 ./scripts/upgrade_acme_site.sh
#   OPENFDD_IMAGE_TAG=3.1.3 ./scripts/upgrade_acme_site.sh --full   # UI build + sync + images
#   OPENFDD_IMAGE_TAG=3.1.3 ./scripts/upgrade_acme_site.sh --skip-backup-prune
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LIMIT="${ACME_ANSIBLE_LIMIT:-acme_vm_bbartling}"
TAG="${OPENFDD_IMAGE_TAG:-3.1.3}"
REMOTE_REPO="${ACME_REMOTE_REPO:-/home/bbartling/open-fdd}"
FULL=0
SKIP_PRUNE=0

usage() {
  sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --limit) LIMIT="$2"; shift 2 ;;
    --tag) TAG="$2"; shift 2 ;;
    --full) FULL=1; shift ;;
    --skip-backup-prune) SKIP_PRUNE=1; shift ;;
    -h|--help) usage 0 ;;
    *) echo "Unknown arg: $1" >&2; usage 1 ;;
  esac
done

export OPENFDD_IMAGE_TAG="$TAG"
ANSIBLE_DIR="${ROOT}/infra/ansible"
INV="${ANSIBLE_INVENTORY:-${ANSIBLE_DIR}/inventory.yml}"

if [[ -f "${ANSIBLE_DIR}/secrets/acme.env.local" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "${ANSIBLE_DIR}/secrets/acme.env.local"
  set +a
  export SSHPASS="${SSHPASS:-}"
fi

if command -v ansible >/dev/null 2>&1; then
  APB="$(command -v ansible)"
elif [[ -x "${ROOT}/.ansible_venv/bin/ansible" ]]; then
  APB="${ROOT}/.ansible_venv/bin/ansible"
else
  echo "ansible not found" >&2
  exit 1
fi

ANSIBLE_SSH_OPTS=(-T 15)

echo "==> Acme site upgrade → ${LIMIT} (image tag ${TAG})"

echo "==> 1/4 Remote backup (workspace preserved on disk)"
"${APB}" -i "$INV" "$LIMIT" "${ANSIBLE_SSH_OPTS[@]}" -m shell -a "cd ${REMOTE_REPO} && ./scripts/openfdd_site_backup.sh"
BACKUP_DIR="$(
  "${APB}" -i "$INV" "$LIMIT" "${ANSIBLE_SSH_OPTS[@]}" -m shell -a "ls -1dt ~/openfdd-backups/*/ 2>/dev/null | head -1" 2>/dev/null \
    | grep -oE '/home/[^[:space:]]+/openfdd-backups/[0-9]{8}-[0-9]{6}' | tail -1 || true
)"
if [[ -n "$BACKUP_DIR" ]]; then
  echo "    Latest backup: $BACKUP_DIR"
else
  echo "    WARN: could not detect latest backup dir on edge" >&2
fi

echo "==> 2/4 Pull GHCR images and recreate containers"
if [[ "$FULL" == "1" ]]; then
  OPENFDD_IMAGE_TAG="$TAG" "${ROOT}/scripts/upgrade_edge_full.sh" --limit "$LIMIT" --skip-ui-build
else
  OPENFDD_IMAGE_TAG="$TAG" RUN_POST_CHECK=0 "${ROOT}/scripts/upgrade_edge_ghcr.sh" --limit "$LIMIT"
fi

if [[ "$SKIP_PRUNE" == "0" ]]; then
  echo "==> 3/4 Prune old edge backup archives (keep latest only)"
  PRUNE_CMD='BACKUP_ROOT="$HOME/openfdd-backups"; latest="$(ls -1dt "$BACKUP_ROOT"/*/ 2>/dev/null | head -1 || true)"; count=0; for d in "$BACKUP_ROOT"/*/; do [[ -d "$d" ]] || continue; if [[ "$d" != "$latest" ]]; then rm -rf "$d"; count=$((count+1)); fi; done; echo "removed ${count} old backup dir(s); kept ${latest:-none}"'
  "${APB}" -i "$INV" "$LIMIT" "${ANSIBLE_SSH_OPTS[@]}" -m shell -a "$PRUNE_CMD"
else
  echo "==> 3/4 Skipping backup prune"
fi

echo "==> 4/4 Post-deploy health check"
"${ANSIBLE_DIR}/scripts/post_deploy_check.sh" --inventory "$INV" --limit "$LIMIT" --http-only

echo ""
echo "OK — Acme upgraded to ${TAG}. Workspace data unchanged under ${REMOTE_REPO}/workspace/"
echo "Optional full validation:"
echo "  OPENFDD_IMAGE_TAG=${TAG} ./scripts/acme_post_deploy_validate.sh --limit ${LIMIT} --quick"
