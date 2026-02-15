#!/bin/bash
#
# BACnet discovery → CSV for the BACnet driver.
# Run this BEFORE starting diy-bacnet-server (only one process can use port 47808).
# Requires: pip install bacpypes3 ifaddr (on the host, not in Docker).
#
# Usage:
#   ./scripts/discover_bacnet.sh 3456789 -o config/bacnet_discovered.csv
#   ./scripts/discover_bacnet.sh 1 3456799 -o config/bacnet_device.csv
#
# Then curate the CSV (remove points not needed for FDD) and start the platform.
# See docs/bacnet/overview.md.

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"
exec python tools/discover_bacnet.py "$@"
