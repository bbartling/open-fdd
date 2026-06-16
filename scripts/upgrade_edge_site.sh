#!/usr/bin/env bash
# Generic edge site upgrade: remote backup → GHCR pull → prune old backups → health check.
#
# Works for any Ansible inventory host (Acme today; more buildings later).
#
#   OPENFDD_IMAGE_TAG=3.1.3 ./scripts/upgrade_edge_site.sh --limit acme_vm_bbartling
#   OPENFDD_IMAGE_TAG=3.1.3 ./scripts/upgrade_edge_site.sh --limit acme_vm_bbartling --full
#   OPENFDD_IMAGE_TAG=3.1.3 ./scripts/upgrade_edge_site.sh --limit acme_vm_bbartling --fast-backup
#   OPENFDD_IMAGE_TAG=3.1.3 ./scripts/upgrade_edge_site.sh --limit acme_vm_bbartling --skip-backup
#
# Environment:
#   OPENFDD_ANSIBLE_LIMIT     default inventory host (optional if --limit passed)
#   OPENFDD_REMOTE_REPO       edge repo path (default /home/<user>/open-fdd)
#   OPENFDD_BACKUP_ASYNC_SECS ansible async budget for remote backup (default 3600)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LIMIT="${OPENFDD_ANSIBLE_LIMIT:-}"
TAG="${OPENFDD_IMAGE_TAG:-3.1.3}"
REMOTE_REPO="${OPENFDD_REMOTE_REPO:-}"
FULL=0
SKIP_PRUNE=0
SKIP_BACKUP=0
FAST_BACKUP=0
BACKUP_ASYNC_SECS="${OPENFDD_BACKUP_ASYNC_SECS:-3600}"

usage() {
  sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --limit) LIMIT="$2"; shift 2 ;;
    --tag) TAG="$2"; shift 2 ;;
    --remote-repo) REMOTE_REPO="$2"; shift 2 ;;
    --full) FULL=1; shift ;;
    --skip-backup-prune) SKIP_PRUNE=1; shift ;;
    --skip-backup) SKIP_BACKUP=1; shift ;;
    --fast-backup) FAST_BACKUP=1; shift ;;
    -h|--help) usage 0 ;;
    *) echo "Unknown arg: $1" >&2; usage 1 ;;
  esac
done

[[ -n "$LIMIT" ]] || { echo "Missing --limit (or set OPENFDD_ANSIBLE_LIMIT)" >&2; usage 1; }

export OPENFDD_IMAGE_TAG="$TAG"
ANSIBLE_DIR="${ROOT}/infra/ansible"
INV="${ANSIBLE_INVENTORY:-${ANSIBLE_DIR}/inventory.yml}"

if [[ -z "$REMOTE_REPO" ]]; then
  REMOTE_REPO="/home/${LIMIT#*_}/open-fdd"
  if [[ "$LIMIT" == acme_vm_bbartling ]]; then
    REMOTE_REPO="/home/bbartling/open-fdd"
  fi
fi

# Optional per-site secrets (e.g. acme.env.local for SSHPASS).
for secrets in "${ANSIBLE_DIR}/secrets/${LIMIT}.env.local" \
  "${ANSIBLE_DIR}/secrets/acme.env.local"; do
  if [[ -f "$secrets" ]]; then
    set -a
    # shellcheck source=/dev/null
    source "$secrets"
    set +a
    export SSHPASS="${SSHPASS:-}"
    break
  fi
done

if command -v ansible >/dev/null 2>&1; then
  APB="$(command -v ansible)"
elif [[ -x "${ROOT}/.ansible_venv/bin/ansible" ]]; then
  APB="${ROOT}/.ansible_venv/bin/ansible"
else
  echo "ansible not found" >&2
  exit 1
fi

ANSIBLE_SSH_OPTS=(-T 30)
ANSIBLE_ASYNC_OPTS=(-B "$BACKUP_ASYNC_SECS" -P 15)

ansible_shell() {
  "${APB}" -i "$INV" "$LIMIT" "${ANSIBLE_SSH_OPTS[@]}" -m shell -a "$1"
}

ansible_shell_bash() {
  "${APB}" -i "$INV" "$LIMIT" "${ANSIBLE_SSH_OPTS[@]}" -m shell -a "/bin/bash -lc $(printf '%q' "$1")"
}

echo "==> Edge site upgrade → ${LIMIT} (image tag ${TAG})"

if [[ "$SKIP_BACKUP" == "0" ]]; then
  echo "==> 1/4 Remote backup (local on edge — no data transfer over Tailscale)"
  BACKUP_ENV="cd ${REMOTE_REPO} && BACKUP_ROOT=~/openfdd-backups/latest"
  if [[ "$FAST_BACKUP" == "1" ]]; then
    BACKUP_ENV+=" BACKUP_INCLUDE_POLL_SAMPLES=0"
  fi
  BACKUP_ENV+=" && ./scripts/openfdd_site_backup.sh"
  echo "    async budget: ${BACKUP_ASYNC_SECS}s (poll every 15s)"
  if ! "${APB}" -i "$INV" "$LIMIT" "${ANSIBLE_SSH_OPTS[@]}" "${ANSIBLE_ASYNC_OPTS[@]}" \
    -m shell -a "$BACKUP_ENV"; then
    echo "ERROR: remote backup failed or timed out" >&2
    echo "Retry: OPENFDD_IMAGE_TAG=${TAG} $0 --limit ${LIMIT} --fast-backup" >&2
    echo "Or skip if a recent backup exists: $0 --limit ${LIMIT} --skip-backup" >&2
    exit 1
  fi
  BACKUP_DIR="$(
    ansible_shell 'echo ~/openfdd-backups/latest' 2>/dev/null \
      | grep -oE '/home/[^[:space:]]+/openfdd-backups/latest' | tail -1 || true
  )"
  if [[ -n "$BACKUP_DIR" ]]; then
    echo "    Rolling backup (overwrite): $BACKUP_DIR"
  else
    echo "    WARN: could not detect backup dir on edge" >&2
  fi
else
  echo "==> 1/4 Skipping remote backup (--skip-backup)"
fi

echo "==> 2/4 Pull GHCR images and recreate containers"
if [[ "$FULL" == "1" ]]; then
  OPENFDD_IMAGE_TAG="$TAG" "${ROOT}/scripts/upgrade_edge_full.sh" --limit "$LIMIT" --skip-ui-build
else
  OPENFDD_IMAGE_TAG="$TAG" RUN_POST_CHECK=0 "${ROOT}/scripts/upgrade_edge_ghcr.sh" --limit "$LIMIT"
fi

if [[ "$SKIP_PRUNE" == "0" ]]; then
  echo "==> 3/4 Remove legacy timestamped edge backups (keep ~/openfdd-backups/latest only)"
  PRUNE_CMD='for d in "$HOME/openfdd-backups"/*/; do [ -d "$d" ] || continue; case "$d" in */latest/) continue ;; esac; rm -rf "$d"; done; echo "kept ~/openfdd-backups/latest"'
  ansible_shell_bash "$PRUNE_CMD"
else
  echo "==> 3/4 Skipping legacy backup cleanup"
fi

echo "==> 4/4 Post-deploy health check"
"${ANSIBLE_DIR}/scripts/post_deploy_check.sh" --inventory "$INV" --limit "$LIMIT" --http-only

echo ""
echo "OK — ${LIMIT} upgraded to ${TAG}. Workspace data unchanged under ${REMOTE_REPO}/workspace/"
echo "Optional full validation:"
echo "  OPENFDD_IMAGE_TAG=${TAG} ./scripts/acme_post_deploy_validate.sh --limit ${LIMIT} --quick"
