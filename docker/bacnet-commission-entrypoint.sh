#!/usr/bin/env bash
set -euo pipefail

export OPENFDD_REPO_ROOT="${OPENFDD_REPO_ROOT:-/app}"
export PYTHONPATH="${PYTHONPATH:-/app}"
export OPENFDD_BACNET_COMMISSION_BIND="${OPENFDD_BACNET_COMMISSION_BIND:-0.0.0.0}"
export OPENFDD_BACNET_COMMISSION_PORT="${OPENFDD_BACNET_COMMISSION_PORT:-8767}"

exec python -m bacnet_toolshed.commission_agent
