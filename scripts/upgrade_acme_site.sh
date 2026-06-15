#!/usr/bin/env bash
# Acme edge wrapper — delegates to generic upgrade_edge_site.sh.
#
#   OPENFDD_IMAGE_TAG=3.1.3 ./scripts/upgrade_acme_site.sh
#   OPENFDD_IMAGE_TAG=3.1.3 ./scripts/upgrade_acme_site.sh --full
#   OPENFDD_IMAGE_TAG=3.1.3 ./scripts/upgrade_acme_site.sh --fast-backup
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LIMIT="${ACME_ANSIBLE_LIMIT:-acme_vm_bbartling}"
REMOTE_REPO="${ACME_REMOTE_REPO:-/home/bbartling/open-fdd}"

exec env \
  OPENFDD_ANSIBLE_LIMIT="$LIMIT" \
  OPENFDD_REMOTE_REPO="$REMOTE_REPO" \
  "${ROOT}/scripts/upgrade_edge_site.sh" \
  --limit "$LIMIT" \
  --remote-repo "$REMOTE_REPO" \
  "$@"
