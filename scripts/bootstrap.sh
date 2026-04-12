#!/usr/bin/env bash
# Open-FDD entry point — keeps all Open-FDD logic in this repo.
# Upstream VOLTTRON Docker lives only under OFDD_VOLTTRON_DOCKER_DIR (default ~/volttron-docker); do not commit Open-FDD changes there.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$ROOT/afdd_stack/scripts/bootstrap.sh" "$@"
