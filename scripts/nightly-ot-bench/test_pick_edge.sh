#!/usr/bin/env bash
# Unit tests for resolve_edge_target (gate 35 pick_edge fix).
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib_pick_edge.sh"

fail=0
assert_eq() {
  local got="$1" want="$2" name="$3"
  if [[ "$got" != "$want" ]]; then
    echo "FAIL: $name — got='$got' want='$want'" >&2
    fail=1
  else
    echo "PASS: $name"
  fi
}

assert_rc() {
  local rc="$1" want="$2" name="$3"
  if [[ "$rc" -ne "$want" ]]; then
    echo "FAIL: $name — rc=$rc want=$want" >&2
    fail=1
  else
    echo "PASS: $name (rc=$want)"
  fi
}

# MEGA FAIL shape: edge present, no site_id, has_telemetry false + EXPECTED_*
JSON_NO_SITE='{"ok":true,"edges":[{"edge_id":"vim-1","has_telemetry":false}]}'
unset EXPECTED_EDGE_ID EXPECTED_SITE_ID OPENFDD_SITE_ID OPENFDD_EDGE_ID || true
export EXPECTED_EDGE_ID=vim-1 EXPECTED_SITE_ID=ACME
out="$(resolve_edge_target "$JSON_NO_SITE")"
assert_eq "$out" "ACME vim-1" "EXPECTED_SITE_ID preferred when edge omits site_id"

# Mismatch: edge reports lab but EXPECTED is ACME → fail closed
JSON_LAB='{"ok":true,"edges":[{"edge_id":"vim-1","site_id":"lab","has_telemetry":true}]}'
set +e
resolve_edge_target "$JSON_LAB" >/dev/null 2>&1
rc=$?
set -e
assert_rc "$rc" 2 "mismatch EXPECTED_SITE_ID vs edge site_id fails closed"

# building_id alias
JSON_BID='{"ok":true,"edges":[{"edge_id":"vim-1","building_id":"ACME","has_telemetry":false}]}'
out="$(resolve_edge_target "$JSON_BID")"
assert_eq "$out" "ACME vim-1" "building_id alias used as site"

# Unresolved with EXPECTED → fail closed (no lab)
JSON_EMPTY='{"ok":true,"edges":[]}'
unset EXPECTED_EDGE_ID || true
export EXPECTED_SITE_ID=ACME
set +e
resolve_edge_target "$JSON_EMPTY" >/dev/null 2>&1
rc=$?
set -e
assert_rc "$rc" 2 "EXPECTED_SITE_ID with no matching edge fails closed"

# Legacy default only when EXPECTED_* unset
unset EXPECTED_EDGE_ID EXPECTED_SITE_ID || true
export OPENFDD_SITE_ID=lab OPENFDD_EDGE_ID=fieldbus-1
out="$(resolve_edge_target "$JSON_EMPTY")"
assert_eq "$out" "lab fieldbus-1" "lab default only without EXPECTED_*"

if [[ "$fail" -ne 0 ]]; then
  echo "test_pick_edge: FAILED" >&2
  exit 1
fi
echo "test_pick_edge: OK"
exit 0
