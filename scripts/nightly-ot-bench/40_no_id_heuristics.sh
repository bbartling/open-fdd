#!/usr/bin/env bash
# Gate 40 — equipment selection is the stamp and mapped roles, not id text.
#
# Offline. No GHCR pull and no hub. A PASS here is not tip+field stress and
# not fully_qualified. Live ACME inclusion (jci_vav_* / opaque AHU on the
# historian) is gate 37 on a pinned tip.
#
# Refs #1037 #1038 #1039 #1040 #1041 #1042 #1045 #1046 #1047
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib.sh"
load_bench_env
cd "$ROOT"

ART="${ARTIFACT_DIR:-$(artifact_dir)}"
mkdir -p "$ART"

hdr "Equipment-id heuristic source gate (#1037–#1047)"

SCAN_OUT="$ART/40_no_id_heuristics.txt"
set +e
python3 "$ROOT/scripts/qualification/no_equipment_id_heuristics.py" >"$SCAN_OUT" 2>&1
scan_rc=$?
python3 "$ROOT/scripts/qualification/no_equipment_id_heuristics.py" --selftest >>"$SCAN_OUT" 2>&1
self_rc=$?
set -e
cat "$SCAN_OUT"

if [[ "$scan_rc" -eq 0 ]]; then
  ok "product source has no equipment_id LIKE / id-text selector"
else
  bad "equipment-id heuristic scan FAIL (see 40_no_id_heuristics.txt)"
fi
if [[ "$self_rc" -eq 0 ]]; then
  ok "scanner selftest flags LIKE and ignores negated assertions"
else
  bad "scanner selftest FAIL"
fi

summary
[[ "$FAIL" -eq 0 ]]
