#!/usr/bin/env bash
# Pre-GHCR / post-bootstrap validation for release 3.2.2+ (issue #402).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_rust_site_lib.sh
source "$ROOT/scripts/openfdd_rust_site_lib.sh"

echo "==> 3.2.2 prep validate (issue #402)"
openfdd_rust_ensure_container_workspace "$ROOT"

if [[ -f "$ROOT/workspace/data.env.local" ]]; then
  grep -q 'OPENFDD_BACNET_MODE=live' "$ROOT/workspace/data.env.local" \
    && echo "OK: OPENFDD_BACNET_MODE=live" \
    || echo "WARN: set OPENFDD_BACNET_MODE=live in workspace/data.env.local"
  grep -q 'OPENFDD_MODBUS_MODE=live' "$ROOT/workspace/data.env.local" \
    && echo "OK: OPENFDD_MODBUS_MODE=live" \
    || echo "WARN: set OPENFDD_MODBUS_MODE=live in workspace/data.env.local"
else
  echo "WARN: workspace/data.env.local missing — bootstrap first"
fi

HAYSTACK_CFG="$ROOT/workspace/data/drivers/local.nhaystack.toml"
if [[ -f "$HAYSTACK_CFG" ]]; then
  echo "OK: Haystack profile present: $HAYSTACK_CFG"
else
  echo "WARN: Haystack gateway needs workspace/data/drivers/local.nhaystack.toml (see docs/development/local_haystack_niagara.md)"
fi

"$ROOT/scripts/openfdd_rust_edge_validate.sh"
echo "Prep validate complete."
