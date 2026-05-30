#!/usr/bin/env bash
# BACnet Who-Is smoke test (BACpypes3 shell pattern — GitHub bacpypes3#125).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT"
export OPENFDD_REPO_ROOT="$ROOT"
exec "${ROOT}/.venv/bin/python" -m bacnet_toolshed.smoke_whois "$@"
