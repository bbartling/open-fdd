#!/usr/bin/env bash
# Local + optional live smoke for #1044 cache/unload classifiers, #1049 disk
# preflight, #1050 series-preview contract, and #1063 health/version fail-fast.
# Exit 0: contracts hold. Exit 1: a contract or a live liveness hang failed.
# This gate is evidence. It does not close the issues and it is not FQ.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$DIR/../.." && pwd)"
ART="${ARTIFACT_DIR:-$ROOT/reports/cache_retention_preview_health_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$ART"
python3 "$ROOT/scripts/qualification/cache_retention_preview_health.py" --artifact-dir "$ART"
