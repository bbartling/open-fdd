#!/usr/bin/env bash
# Render the unqualified OT archive compose file. Does not boot or pull.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "${OPENFDD_OT_ARCHIVE_RESTORE:-}" != "1" ]]; then
  echo "Refusing restore: set OPENFDD_OT_ARCHIVE_RESTORE=1 (explicit archive lane)." >&2
  exit 2
fi
if [[ "${1:-}" == "--boot" ]]; then
  echo "SoftOPEN defer: isolated boot, health, and replay were not qualified for this snapshot." >&2
  echo "See ${ROOT}/evidence/MISSING.md" >&2
  exit 2
fi
export OPENFDD_OT_ARCHIVE_TAG="${OPENFDD_OT_ARCHIVE_TAG:?set OPENFDD_OT_ARCHIVE_TAG to an explicit tag or digest}"
docker compose -f "${ROOT}/recipes/compose.ot-archive.yml" config
echo "Rendered only. No containers were started. 4.0 databases are out of scope."
