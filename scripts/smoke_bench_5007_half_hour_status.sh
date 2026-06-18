#!/usr/bin/env bash
# Read-only half-hour bench smoke status — safe for Cursor agents.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "${ROOT}/scripts/smoke_paired_fdd_status.sh" --mode short "$@"
