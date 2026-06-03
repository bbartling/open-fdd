#!/usr/bin/env bash
set -euo pipefail

# Commission agent may write commission.env / points CSV as root on bind mounts.
WS="${OPENFDD_WORKSPACE_DIR:-/var/openfdd/workspace}"
if [[ -d "$WS/bacnet" ]]; then
  chown -R "$(stat -c '%u:%g' "$WS" 2>/dev/null || echo '1000:1000')" "$WS/bacnet" 2>/dev/null || \
    chown -R 1000:1000 "$WS/bacnet" 2>/dev/null || true
fi

export OPENFDD_REPO_ROOT="${OPENFDD_REPO_ROOT:-/app}"
export PYTHONPATH="${PYTHONPATH:-/app}"
export OPENFDD_BACNET_COMMISSION_BIND="${OPENFDD_BACNET_COMMISSION_BIND:-0.0.0.0}"
export OPENFDD_BACNET_COMMISSION_PORT="${OPENFDD_BACNET_COMMISSION_PORT:-8767}"

exec python -m bacnet_toolshed.commission_agent
