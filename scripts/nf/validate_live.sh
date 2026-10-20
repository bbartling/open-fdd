#!/usr/bin/env bash
# Live bosspi read. See scripts/nf/validate_live.py for the environment.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
exec python3 "$root/scripts/nf/validate_live.py" "$@"
