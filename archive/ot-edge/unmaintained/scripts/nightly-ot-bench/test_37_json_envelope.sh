#!/usr/bin/env bash
# Gate 37 must not feed a truncated body to JSON parsers.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$DIR/../.." && pwd)"
OPENFDD_GATE37_SOURCE_FUNCS=1
# shellcheck disable=SC1091
source "$DIR/37_acme_analytics_charts.sh"

fail=0
pass() { echo "PASS: $1"; }
bad() { echo "FAIL: $1" >&2; fail=1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

python3 - "$TMP/envelope.json" <<'PY'
import json, sys
points = [
    {"equipment_id": "AC_1", "pad": "x" * 48, "i": i}
    for i in range(180)
]
with open(sys.argv[1], "w", encoding="utf-8") as fh:
    json.dump({"analytics": {"points": points, "coverage": {"fail_closed": False}}}, fh)
PY
raw_bytes="$(wc -c <"$TMP/envelope.json" | tr -d '[:space:]')"
if [[ "$raw_bytes" -le 8192 ]]; then
  bad "fixture must exceed 8192 bytes (got $raw_bytes)"
else
  pass "fixture is ${raw_bytes} bytes"
fi

cp "$TMP/envelope.json" "$TMP/kept.json"
keep_or_truncate_probe_body "$TMP/kept.json"
if grep -q '…(truncated)' "$TMP/kept.json"; then
  bad "JSON envelope was truncated"
else
  pass "JSON envelope was not truncated"
fi
python3 -c 'import json,sys; json.load(open(sys.argv[1], encoding="utf-8"))' "$TMP/kept.json"
jq -e '.analytics.coverage.fail_closed == false' "$TMP/kept.json" >/dev/null
pass "kept envelope parses as JSON (python and jq)"

EQ="$TMP/equipment.json"
printf '%s\n' '{"equipment":[{"equipment_id":"AC_1","equipType":"ahu"}]}' >"$EQ"
set +e
heur="$(python3 "$ROOT/scripts/qualification/no_equipment_id_heuristics.py" \
  --check-preset ahu \
  --envelope "$TMP/kept.json" \
  --equipment-json "$EQ" 2>&1)"
heur_rc=$?
set -e
if [[ "$heur_rc" -ne 0 ]]; then
  bad "heuristics parser rc=$heur_rc: $heur"
else
  pass "heuristics --envelope accepted the full JSON body"
fi

# The old cut (4096 bytes + marker) is what raised JSONDecodeError near char 4106.
head -c 4096 "$TMP/envelope.json" >"$TMP/cut.json"
echo "…(truncated)" >>"$TMP/cut.json"
set +e
python3 -c 'import json,sys; json.load(open(sys.argv[1], encoding="utf-8"))' "$TMP/cut.json" 2>"$TMP/cut.err"
cut_rc=$?
set -e
if [[ "$cut_rc" -eq 0 ]]; then
  bad "truncated fixture unexpectedly parsed"
else
  pass "truncated fixture is invalid JSON (the ART failure mode)"
fi

python3 - "$TMP/bom.json" <<'PY'
from pathlib import Path
import sys
Path(sys.argv[1]).write_bytes(b"\xef\xbb\xbf" + b'{"equipment_id":"AC_1","pad":"' + b"y" * 9000 + b'"}')
PY
keep_or_truncate_probe_body "$TMP/bom.json"
if grep -q '…(truncated)' "$TMP/bom.json"; then
  bad "UTF-8 BOM JSON object was truncated"
else
  pass "UTF-8 BOM JSON object was kept"
fi

python3 - "$TMP/array.json" <<'PY'
from pathlib import Path
import sys
Path(sys.argv[1]).write_bytes(b"\n  " + b'[{"equipment_id":"AC_1"}]' + b" " * 9000)
PY
keep_or_truncate_probe_body "$TMP/array.json"
if grep -q '…(truncated)' "$TMP/array.json"; then
  bad "whitespace-prefixed JSON array was truncated"
else
  pass "whitespace-prefixed JSON array was kept"
fi
python3 -c 'import json,sys; json.load(open(sys.argv[1], encoding="utf-8"))' "$TMP/array.json"

python3 - "$TMP/html.json" <<'PY'
from pathlib import Path
import sys
Path(sys.argv[1]).write_text("<html><body>" + ("gateway " * 2000) + "</body></html>\n", encoding="utf-8")
PY
keep_or_truncate_probe_body "$TMP/html.json"
html_bytes="$(wc -c <"$TMP/html.json" | tr -d '[:space:]')"
if grep -q '…(truncated)' "$TMP/html.json" && [[ "$html_bytes" -lt 8192 ]]; then
  pass "HTML 502 artifact still truncated ($html_bytes bytes)"
else
  bad "HTML artifact was not truncated (bytes=$html_bytes)"
fi

printf '%s\n' '{"ok":true}' >"$TMP/small.json"
before="$(cat "$TMP/small.json")"
keep_or_truncate_probe_body "$TMP/small.json"
after="$(cat "$TMP/small.json")"
if [[ "$before" == "$after" ]]; then
  pass "small JSON body unchanged"
else
  bad "small JSON body changed"
fi

if [[ "$fail" -ne 0 ]]; then
  echo "test_37_json_envelope: FAILED" >&2
  exit 1
fi
echo "test_37_json_envelope: OK"
exit 0
