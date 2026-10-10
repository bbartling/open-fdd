#!/usr/bin/env bash
# Offline controls for T1h harness (no stack required).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PY="$ROOT/scripts/ops/local_memory_ingest_bench.py"

python3 - <<'PY' "$PY"
import importlib.util, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("bench", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
sys.modules["bench"] = mod
spec.loader.exec_module(mod)

# mintbench must never allow 8 GiB central
p = mod.PROFILES["mintbench-3g"]
assert p.allow_8g_central is False
host = mod.HostSnapshot("mintbench", 7 * mod.GIB, 6 * mod.GIB, 6)
ok, detail = mod.profile_fit(host, mod.PROFILES["mintbench-3g"])
assert ok, detail
ok8, detail8 = mod.profile_fit(host, mod.Profile("bad8", 8 * mod.GIB, 8 * mod.GIB, False))
assert not ok8 and "8 GiB" in detail8, detail8

# 32 GB host can fit 4 GiB then 8 GiB profiles when available
host32 = mod.HostSnapshot("bench", 32 * mod.GIB, 24 * mod.GIB, 8)
assert mod.profile_fit(host32, mod.PROFILES["bench32-4g"])[0]
assert mod.profile_fit(host32, mod.PROFILES["bench32-8g"])[0]

# Fixture hashes against known lab root when present
root = Path("/home/ben/Documents/buildings100_and_50")
if root.is_dir():
    r = mod.phase_fixture_hashes(root)
    assert r.status in {"PASS", "BLOCKED"}, r
    print("fixture_hashes", r.status, r.detail)
else:
    print("fixture_hashes SKIP (root absent)")

print("PASS offline T1h harness controls")
PY

# Preflight-only dry run on this host (may BLOCKED if docker missing — that is honest)
set +e
OUT="$(mktemp -d)"
python3 "$PY" --profile mintbench-3g --phases preflight,fixture_hashes --out "$OUT" >/tmp/t1h_preflight.json
RC=$?
set -e
echo "preflight_rc=$RC summary=$OUT/SUMMARY.json"
python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["verdict"])' "$OUT/SUMMARY.json"
echo "PASS test_local_memory_ingest_bench.sh"
