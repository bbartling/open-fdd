#!/usr/bin/env bash
# Host wrapper for scripts/openfdd_disk_preflight.py.
# Exit 0 proceed, 10 skip backup, 11 prune then backup, 20 fail closed.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$ROOT/scripts/openfdd_disk_preflight.py" "$@"
