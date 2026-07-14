#!/usr/bin/env bash
# Fail if central or edge Cargo.toml directly depends on bacnet-* crates.
# Field-bus BACnet wire must live only in services/fieldbus.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

check_no_bacnet_deps() {
  local label="$1"
  local cargo_toml="$2"
  if [[ ! -f "$cargo_toml" ]]; then
    echo "architecture gate: missing $cargo_toml" >&2
    return 1
  fi
  if rg -n '^[[:space:]]*bacnet-[A-Za-z0-9_-]+[[:space:]]*=' "$cargo_toml" >/tmp/openfdd_bacnet_dep_hits.txt 2>/dev/null; then
    echo "architecture gate FAILED: $label must not depend on bacnet-* crates" >&2
    echo "  file: $cargo_toml" >&2
    cat /tmp/openfdd_bacnet_dep_hits.txt >&2
    return 1
  fi
  return 0
}

failed=0
check_no_bacnet_deps "services/central" "$ROOT/services/central/Cargo.toml" || failed=1
check_no_bacnet_deps "edge" "$ROOT/edge/Cargo.toml" || failed=1

if [[ "$failed" -ne 0 ]]; then
  echo "Remedy: remove bacnet-* dependencies; use openfdd-fieldbus + MQTTS ingest instead." >&2
  exit 1
fi

echo "architecture gate OK: central and edge have no direct bacnet-* Cargo dependencies"
