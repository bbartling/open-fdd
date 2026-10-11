#!/usr/bin/env bash
# Offline controls for T1h/T6a harness (no stack required). Soft-OPEN 371 T0b.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PY="$ROOT/scripts/ops/local_memory_ingest_bench.py"

python3 - <<'PY' "$PY"
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import zipfile
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

# 32 GB host: shared ceiling min(40% total, 50% available) blocks oversized combined
host32 = mod.HostSnapshot("bench", 32 * mod.GIB, 24 * mod.GIB, 8)
assert mod.profile_fit(host32, mod.PROFILES["bench32-4g"])[0]
assert mod.profile_fit(host32, mod.PROFILES["bench32-8g"])[0]
host_tight = mod.HostSnapshot("synthetic-bench", 32 * mod.GIB, 17 * mod.GIB, 8)
ok_over, detail_over = mod.profile_fit(host_tight, mod.PROFILES["bench32-8g"])
assert not ok_over, detail_over  # 10 GiB combined > 8.5 GiB shared ceiling

# --- Soft-OPEN 371 counterexamples: broken fixtures must FAIL (was false PASS) ---
with tempfile.TemporaryDirectory(prefix="t371-eval-") as dirname:
    root = Path(dirname)
    with zipfile.ZipFile(root / "BUILDING_50_openfdd.zip", "w") as zf:
        zf.writestr(
            "TEST_BUILDING/AHU_1/history_wide.csv",
            "timestamp_utc,temp\n2026-07-17 11:00:00+00:00,72\n",
        )
    (root / "BUILDING_100_openfdd.zip").write_bytes(b"this is not a zip archive")

    # First counterexample: zero-written truthy merges must FAIL
    responses = iter(
        [
            (200, {"ok": True, "total_rows": 1, "building_id": "TEST_BUILDING"}),
            (
                200,
                {
                    "ok": True,
                    "total_rows": 0,
                    "equipment_written": 0,
                    "merges": [{"rows_written": 0, "skipped": 100, "status": "timeout"}],
                },
            ),
        ]
    )
    calls = []

    def fake_http(method, url, **kwargs):
        calls.append({"method": method, "path": url})
        return next(responses)

    mod.http_json = fake_http
    r = mod.phase_seed_append("https://offline.invalid", "offline-unused-token", root)
    assert r.status == "FAIL", r
    assert "positive typed" in r.detail or "durable" in r.detail, r.detail
    print("counterexample_fixed zero_committed_truthy_merges", r.status, r.detail)

    for case, seed, append in [
        ("negative_counts", {"ok": True, "total_rows": -1}, {"ok": True, "total_rows": -1}),
        (
            "string_zero_counts",
            {"ok": True, "total_rows": "0"},
            {"ok": True, "equipment_written": "0"},
        ),
        (
            "partial_timeout_positive_counts",
            {
                "ok": True,
                "total_rows": 1,
                "status": "partial",
                "timed_out": True,
                "building_id": "TEST_BUILDING",
            },
            {
                "ok": True,
                "total_rows": 1,
                "status": "cancelled",
                "timed_out": True,
            },
        ),
    ]:
        seq = iter([(200, seed), (200, append)])

        def fake_case(method, url, _seq=seq, **kwargs):
            return next(_seq)

        mod.http_json = fake_case
        r = mod.phase_seed_append("https://offline.invalid", "tok", root)
        assert r.status == "FAIL", (case, r)
        print("counterexample_fixed", case, r.status)

    # Health: boolean / inconsistent fields FAIL
    mod.http_json = lambda *a, **k: (
        200,
        {
            "version": "wrong-candidate",
            "memory_budget": dict.fromkeys(
                ["hard_limit_bytes", "current_bytes", "peak_bytes", "sample_ms", "source"],
                False,
            ),
        },
    )
    r = mod.phase_health_honesty("https://offline.invalid", "tok")
    assert r.status == "FAIL", r
    print("counterexample_fixed invalid_health_boolean_fields", r.status)

    mod.http_json = lambda *a, **k: (
        200,
        {
            "version": "3.5.71+b146d4ce048b",
            "memory_budget": {
                "hard_limit_bytes": 1,
                "current_bytes": 2,
                "peak_bytes": 0,
                "sample_ms": 0,
                "source": "",
            },
        },
    )
    r = mod.phase_health_honesty("https://offline.invalid", "tok")
    assert r.status == "FAIL", r
    print("counterexample_fixed invalid_health_zero_and_inconsistent_peak", r.status)

    # Corrupt zip must FAIL (not hash-only PASS)
    fixture = mod.phase_fixture_hashes(root)
    assert fixture.status == "FAIL", fixture
    print("counterexample_fixed corrupt_fixture_hash_only", fixture.status)

    # Explicit pressure stub must FAIL with non-zero exit (was PARTIAL rc0)
    out = root / "explicit_pressure"
    original_argv = sys.argv
    sys.argv = [
        str(sys.argv[1]),
        "--profile",
        "mintbench-3g",
        "--fixture-root",
        str(root),
        "--phases",
        "fixture_hashes,pressure",
        "--out",
        str(out),
    ]
    with contextlib.redirect_stdout(io.StringIO()):
        rc = mod.main()
    sys.argv = original_argv
    summary = json.loads((out / "SUMMARY.json").read_text())
    pressure = next(p for p in summary["phases"] if p["phase"] == "pressure")
    assert rc == 2 and summary["verdict"] == "FAIL", (rc, summary["verdict"], pressure)
    assert pressure["status"] == "FAIL", pressure
    print("counterexample_fixed explicit_pressure_still_stub", rc, pressure["status"])

    # Positive path: typed seed+append + durable readback PASS
    with zipfile.ZipFile(root / "BUILDING_100_openfdd.zip", "w") as zf:
        zf.writestr(
            "TEST_BUILDING/AHU_1/history_wide.csv",
            "timestamp_utc,temp\n2026-07-17 11:00:00+00:00,72\n",
        )
    fixture_ok = mod.phase_fixture_hashes(root)
    assert fixture_ok.status == "PASS", fixture_ok

    good = iter(
        [
            (200, {"ok": True, "total_rows": 10, "building_id": "TEST_BUILDING"}),
            (200, {"ok": True, "total_rows": 1, "equipment_written": 1}),
            (200, {"ok": True, "buildings": ["TEST_BUILDING"]}),
            (200, {"ok": True, "equipment": [{"equipment_id": "AHU_1"}]}),
        ]
    )
    mod.http_json = lambda *a, **k: next(good)
    r = mod.phase_seed_append("https://offline.invalid", "tok", root)
    assert r.status == "PASS", r
    assert "durable_readback" in r.metrics
    print("positive_seed_append", r.status)

print("PASS offline Soft-OPEN 371 T0b evaluator controls")
PY

# Preflight-only dry run on this host (may BLOCKED if docker missing — that is honest)
set +e
OUT="$(mktemp -d)"
python3 "$PY" --profile mintbench-3g --phases preflight,fixture_hashes --out "$OUT" >/tmp/t1h_preflight.json
RC=$?
set -e
echo "preflight_rc=$RC summary=$OUT/SUMMARY.json"
VERDICT="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["verdict"])' "$OUT/SUMMARY.json")"
echo "preflight_verdict=$VERDICT"
# CONTROL_ONLY (fixtures present) or BLOCKED (docker/fixtures) are honest; FAIL is not.
case "$VERDICT" in
  CONTROL_ONLY|BLOCKED|PARTIAL) ;;
  *) echo "unexpected preflight verdict $VERDICT"; exit 1 ;;
esac
echo "PASS test_local_memory_ingest_bench.sh"
