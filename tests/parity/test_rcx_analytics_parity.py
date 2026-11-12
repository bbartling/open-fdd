"""pandas (open_fdd.analytics.core) == the NF app's JS maths for the two RCx run-hours calculations (#1598).

Both run on the seeded parity generator (``generate(seed=0, equips=2, days=14, profile="basic")``, SI, 5-minute grid):

* weekly motor run hours + mean OAT while on (``motor_run_hours_weekly`` vs ``rcxOverviewMath.weeklyRuntime``), and
* mechanical cooling hours per SI outdoor-air bin (``mech_cooling_oat_bins`` vs ``rcxOverviewMath.mechBins``).

Needs pandas and node; skipped without them.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

from open_fdd.parity import dataset  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "tests" / "parity" / "rcx_js_runner.mjs"
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node required")


@pytest.fixture(scope="module")
def data():
    ds = dataset.generate(seed=0, equips=2, days=14, profile="basic")
    df = pd.DataFrame(ds.history)
    df["timestamp_utc"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    frames, nested = {}, {}
    for eq, g in df.groupby("equipment_id"):
        f = g.drop(columns=["equipment_id", "ts"]).set_index("timestamp_utc").sort_index()
        f.attrs.update({"equipment_type": "AHU", "poll_seconds": 300})
        frames[eq] = f
        nested[eq] = {role: col for col, role in ds.role_map.items() if col in f.columns}
        nested[eq]["equipment_type"] = "AHU"
    return ds, df, frames, nested


@pytest.fixture(scope="module")
def js(data):
    ds, df, _, _ = data
    equips = {}
    for eq, g in df.groupby("equipment_id"):
        g = g.sort_values("ts")
        nn = lambda col: [None if pd.isna(v) else float(v) for v in g[col]]  # noqa: E731
        equips[eq] = {"t": [int(t) for t in g["ts"]], "fan": nn("fan_status"), "comp": nn("compressor_status"), "oat": nn("oa_t"), "web": nn("web_oa_t")}
    r = subprocess.run(["node", str(RUNNER)], input=json.dumps({"equips": equips}), capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def test_weekly_run_hours_and_mean_oat_match(data, js):
    from open_fdd.analytics.core import motor_run_hours_weekly

    _, _, frames, nested = data
    # the weekly chart averages the equip's own oa_t (the cooling bins prefer web outdoor air): same policy on both sides
    w = motor_run_hours_weekly(frames, nested, prefer_web_oat=False)
    fan = w[(w["plant_group"] == "air") & (w["signal"] == "fan-status")]
    assert set(fan["equipment_id"]) == {"AHU-1", "AHU-2"}
    for _, row in fan.iterrows():
        jw = js[row["equipment_id"]]["weekly"][str(int(row["week_start"].value // 10**6))]
        assert abs(row["hours"] - jw["hours"]) < 0.006, (row["equipment_id"], row["week_label"])
        assert abs(row["avg_oat_c"] - jw["oat"]) < 1e-6, (row["equipment_id"], row["week_label"])
        assert bool(row["partial_week"]) == bool(jw["partial"])
    # regression anchor from the issue: the healthy unit runs 14 h/day, so 98.0 h in each full week
    full = fan[(fan["equipment_id"] == "AHU-1") & ~fan["partial_week"]]
    assert len(full) >= 2 and all(abs(h - 98.0) < 1e-9 for h in full["hours"])


def test_weekly_uses_interval_durations_with_the_3600_s_cap(data):
    """A 2 h hole is unknown (not clipped, not poll-filled); samples 5 min apart count 5 min each."""
    from open_fdd.analytics.core import motor_run_hours_weekly

    idx = pd.date_range("2026-01-05", periods=48, freq="5min", tz="UTC").delete(range(12, 36))   # 1 h on, then a 2 h hole, then 1 h on
    f = pd.DataFrame({"fan_status": 1.0, "oa_t": 10.0}, index=idx)
    f.attrs.update({"equipment_type": "AHU", "poll_seconds": 300})
    w = motor_run_hours_weekly({"A": f}, {"A": {"fan-status": "fan_status", "outside-air-temp": "oa_t", "equipment_type": "AHU"}})
    row = w[w["signal"] == "fan-status"].iloc[0]
    # 11 intervals of 5 min before the hole (the 12th runs into the hole and is dropped), 11 after, the last sample has none
    assert abs(row["hours"] - (11 + 11) * 300 / 3600) < 0.01
    assert "avg_oat_c" in w.columns and "avg_oat_f" not in w.columns


def test_mech_cooling_bins_match(data, js):
    from open_fdd.analytics.core import mech_cooling_oat_bins

    _, _, frames, nested = data
    b = mech_cooling_oat_bins(frames, nested, prefer_web_oat=True)          # must run: the broken _role_series_unit import is gone
    assert not b.empty
    ind = b[b["series_kind"] == "individual_device"]
    for eq in ("AHU-1", "AHU-2"):
        jm = js[eq]["mech"]
        py = dict(zip(ind[ind["equipment_id"] == eq]["bin_label"], ind[ind["equipment_id"] == eq]["hours"]))
        assert jm["labels"] == ["<10", "10-16", "16-21", "21-27", "27-32", ">=32"]
        for label, hours in zip(jm["labels"], jm["hours"]):
            assert abs(py.get(label, 0.0) - hours) < 0.006, (eq, label)
        assert sum(py.values()) > 0
