#!/usr/bin/env bash
# Run architecture, security, contract, and release smoke gates for central+fieldbus cutover.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

QUICK=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --quick)
      QUICK=1
      shift
      ;;
    -h|--help)
      echo "Usage: $0 [--quick]"
      echo "  --quick  skip cargo test/check gates (file-only gates still run)"
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
  esac
done

GATES_DIR="$ROOT/scripts/gates"
RELEASE_DIR="$ROOT/scripts/release"

run_gate() {
  local script="$1"
  echo ""
  bash "$script"
}

echo "== Open-FDD run_all_gates (quick=$QUICK) =="

run_gate "$GATES_DIR/architecture_no_central_fieldwire.sh"
run_gate "$GATES_DIR/no_anonymous_mqtt.sh"
run_gate "$GATES_DIR/sole_bacnet_udp_owner.sh"

if [[ "$QUICK" -eq 1 ]]; then
  echo ""
  echo "SKIP cargo gates (--quick): mqtt_contract_unit, openapi_central_present"
else
  run_gate "$GATES_DIR/mqtt_contract_unit.sh"
  run_gate "$GATES_DIR/openapi_central_present.sh"
fi

run_gate "$RELEASE_DIR/smoke_standalone_mqtts.sh"

echo ""
echo "PASS: all gates"
