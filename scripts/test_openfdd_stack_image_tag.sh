#!/usr/bin/env bash
# Regression: OPENFDD_IMAGE_TAG must win over sticky OPENFDD_*_IMAGE nightlies.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_stack_lib.sh
source "$ROOT/scripts/openfdd_stack_lib.sh"

# Stale shell leftovers from a prior nightly pull.
export OPENFDD_CENTRAL_IMAGE=ghcr.io/bbartling/openfdd-central:nightly
export OPENFDD_WEB_IMAGE=ghcr.io/bbartling/openfdd-web:nightly
export OPENFDD_MQTT_IMAGE=ghcr.io/bbartling/openfdd-mqtt:nightly
export OPENFDD_FIELDBUS_IMAGE=ghcr.io/bbartling/openfdd-fieldbus:nightly
export OPENFDD_MCP_IMAGE=ghcr.io/bbartling/openfdd-mcp:nightly

export OPENFDD_IMAGE_TAG=sha-deadbeef
openfdd_stack_export_image_env

[[ "$OPENFDD_CENTRAL_IMAGE" == "ghcr.io/bbartling/openfdd-central:sha-deadbeef" ]]
[[ "$OPENFDD_WEB_IMAGE" == "ghcr.io/bbartling/openfdd-web:sha-deadbeef" ]]
[[ "$OPENFDD_MQTT_IMAGE" == "ghcr.io/bbartling/openfdd-mqtt:sha-deadbeef" ]]
[[ "$OPENFDD_FIELDBUS_IMAGE" == "ghcr.io/bbartling/openfdd-fieldbus:sha-deadbeef" ]]
[[ "$OPENFDD_MCP_IMAGE" == "ghcr.io/bbartling/openfdd-mcp:sha-deadbeef" ]]

# Custom non-GHCR override preserved when IMAGE_TAG set.
export OPENFDD_CENTRAL_IMAGE=registry.example/openfdd-central:dev
export OPENFDD_IMAGE_TAG=sha-cafe
openfdd_stack_export_image_env
[[ "$OPENFDD_CENTRAL_IMAGE" == "registry.example/openfdd-central:dev" ]]
[[ "$OPENFDD_WEB_IMAGE" == "ghcr.io/bbartling/openfdd-web:sha-cafe" ]]

# Without IMAGE_TAG, unset vars default to nightly; sticky custom stays.
unset OPENFDD_IMAGE_TAG
unset OPENFDD_MQTT_IMAGE
export OPENFDD_CENTRAL_IMAGE=registry.example/openfdd-central:dev
openfdd_stack_export_image_env
[[ "$OPENFDD_CENTRAL_IMAGE" == "registry.example/openfdd-central:dev" ]]
[[ "$OPENFDD_MQTT_IMAGE" == "ghcr.io/bbartling/openfdd-mqtt:nightly" ]]

echo "PASS openfdd_stack_export_image_env tip pin + custom override"

# Local / unmerged frontend must not silently pull GHCR web.
export OPENFDD_WEB_IMAGE=ghcr.io/bbartling/openfdd-web:sha-deadbeef
if openfdd_stack_frontend_unmerged "$ROOT"; then
  if openfdd_stack_guard_ghcr_web; then
    echo "FAIL: guard allowed GHCR web while frontend/web drifted" >&2
    exit 1
  fi
  OPENFDD_ALLOW_STALE_GHCR_WEB=1 openfdd_stack_guard_ghcr_web
else
  echo "NOTE: frontend/web matches master — skip drift-guard fail path"
fi
export OPENFDD_WEB_IMAGE=openfdd-web:overview-vibe19-oracle
unset OPENFDD_ALLOW_STALE_GHCR_WEB
openfdd_stack_guard_ghcr_web
echo "PASS openfdd_stack_guard_ghcr_web refuses stale GHCR web"
