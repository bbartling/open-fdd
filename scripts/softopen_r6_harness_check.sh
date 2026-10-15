#!/usr/bin/env bash
# Soft-OPEN R6/R8c harness — smoke + pack pin (≠ equation FQ).
# Installed-source checksum/size must match the contract ledger — no silent drift.
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

# 2) Analytics pack version Soft-OPEN + aligned with contract_version prefix.
pack_ver=$(python3 -c 'import json;print(json.load(open("sql/analytics/registry.json"))["pack_version"])')
contract_ver=$(python3 -c 'import json;print(json.load(open("sql/contract/manifest.json"))["contract_version"])')
bundle_ver=$(python3 -c 'import json;print(json.load(open("sql/contract/successor_bundle/manifest.softopen.json"))["bundle_version"])')
if [[ "$pack_ver" != *softopen* ]]; then
  echo "FAIL: analytics pack_version missing softopen ($pack_ver)"
  fail=1
elif [[ "$pack_ver" != "$contract_ver" ]]; then
  echo "FAIL: analytics pack_version ($pack_ver) != contract_version ($contract_ver)"
  fail=1
elif [[ "$bundle_ver" != "$contract_ver" ]]; then
  echo "FAIL: successor bundle_version ($bundle_ver) != contract_version ($contract_ver)"
  fail=1
else
  echo "OK: analytics pack_version=$pack_ver (aligned with contract + successor)"
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

# 6) Installed-source checksum/size vs contract manifest (FAIL on drift — no silent accept).
python3 <<'PY' || fail=1
import hashlib, json, sys
from pathlib import Path

m = json.loads(Path("sql/contract/manifest.json").read_text(encoding="utf-8"))
files = m.get("files") or []
if len(files) != int(m.get("file_count") or -1):
    print(f"FAIL: file_count {m.get('file_count')} != len(files) {len(files)}")
    sys.exit(1)

ledger_path = Path("sql/contract/successor_bundle/FILES.sha256")
ledger = {}
for line in ledger_path.read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    sha, path = line.split(None, 1)
    ledger[path] = sha

h = hashlib.sha256()
drift = []
for entry in files:
    path = entry["path"]
    p = Path(path)
    if not p.is_file():
        drift.append(f"MISSING {path}")
        continue
    data = p.read_bytes()
    dig = hashlib.sha256(data).hexdigest()
    if dig != entry.get("sha256") or len(data) != int(entry.get("bytes") or -1):
        drift.append(
            f"{path}: manifest sha/bytes={entry.get('sha256','')[:16]}…/{entry.get('bytes')} "
            f"disk={dig[:16]}…/{len(data)}"
        )
    if ledger.get(path) != dig:
        drift.append(f"{path}: FILES.sha256 mismatch (ledger={ledger.get(path,'MISSING')[:16]}…)")
    h.update(path.encode())
    h.update(b"\0")
    h.update(dig.encode())
    h.update(b"\0")

pack = h.hexdigest()
if pack != m.get("pack_sha256"):
    drift.append(
        f"pack_sha256: manifest={m.get('pack_sha256')} recomputed_from_disk={pack}"
    )

extra = set(ledger) - {e["path"] for e in files}
missing_ledger = {e["path"] for e in files} - set(ledger)
if extra:
    drift.append(f"FILES.sha256 extras: {sorted(extra)[:5]}")
if missing_ledger:
    drift.append(f"FILES.sha256 missing: {sorted(missing_ledger)[:5]}")

if drift:
    print("FAIL: installed contract checksum/size drift (no silent accept):")
    for row in drift:
        print(f"  - {row}")
    sys.exit(1)
print(f"OK: installed checksum/size match ({len(files)} files, pack_sha256 pin)")
PY

# 7) C2 FDD SQL checksum compare (77 rules + registry vs contract; optional BPS vendor).
#    Canonical pack is sql/fdd — not legacy sql_rules/. Soft-OPEN ≠ FQ.
if ! python3 "$ROOT/scripts/sql_fdd_bps_checksum_compare.py"; then
  echo "FAIL: C2 sql_fdd_bps_checksum_compare"
  fail=1
else
  echo "OK: C2 FDD SQL checksum compare"
fi

if [[ "$fail" -ne 0 ]]; then
  echo "Soft-OPEN harness FAILED"
  exit 1
fi
echo "Soft-OPEN harness PASS (smoke pin only — Soft-OPEN ≠ FQ)"
