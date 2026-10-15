#!/usr/bin/env bash
# Soft-OPEN R6/R8c harness — smoke + pack pin (≠ equation FQ).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

fail=0
echo "== Soft-OPEN harness (≠ FQ) =="

# 1) Contract original warehouse hash must remain immutable.
ORIG='0597b6d6492750edae2c994ac5d2fcbb26a8a2bd6c122013da5399b94b8b24ec'
got=$(python3 -c 'import json;from pathlib import Path;m=json.loads(Path("sql/contract/successor_bundle/manifest.softopen.json").read_text());print(m["preserve_original_warehouse"]["sha256"])')
if [[ "$got" != "$ORIG" ]]; then
  echo "FAIL: original warehouse sha256 mutated"
  fail=1
else
  echo "OK: original warehouse sha256 preserved"
fi

# 2) Analytics pack version Soft-OPEN.
pack_ver=$(python3 -c 'import json;print(json.load(open("sql/analytics/registry.json"))["pack_version"])')
if [[ "$pack_ver" != *softopen* ]]; then
  echo "FAIL: analytics pack_version missing softopen ($pack_ver)"
  fail=1
else
  echo "OK: analytics pack_version=$pack_ver"
fi

# 3) Contract soft_open_neq_fq flag.
python3 -c 'import json;m=json.load(open("sql/contract/manifest.json"));assert m.get("soft_open_neq_fq") is True;assert m.get("engine")=="timescale/postgresql";print("OK: contract Soft-OPEN flags")' || fail=1

# 4) Registry rule count (77 smoke surface).
n=$(grep -cE '^[[:space:]]*-[[:space:]]*rule_id:' sql/fdd/registry.yaml || true)
if [[ "$n" != "77" ]]; then
  echo "FAIL: registry rules=$n (want 77)"
  fail=1
else
  echo "OK: registry rules=77"
fi

# 5) Successor bundle FILES ledger present.
if [[ ! -f sql/contract/successor_bundle/FILES.sha256 ]]; then
  echo "FAIL: missing successor_bundle/FILES.sha256"
  fail=1
else
  echo "OK: successor_bundle/FILES.sha256 present ($(wc -l < sql/contract/successor_bundle/FILES.sha256) lines)"
fi

if [[ "$fail" -ne 0 ]]; then
  echo "Soft-OPEN harness FAILED"
  exit 1
fi
echo "Soft-OPEN harness PASS (smoke pin only — Soft-OPEN ≠ FQ)"
