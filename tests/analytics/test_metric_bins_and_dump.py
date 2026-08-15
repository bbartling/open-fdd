"""Pandas analytics metric OAT bins and dump_tables contract."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from open_fdd.analytics import DUMP_FILENAMES, dump_tables, mech_cooling_oat_bins


def _chiller_frame(*, oat_f: float) -> dict:
    idx = pd.date_range("2026-01-01", periods=12, freq="5min", tz="UTC")
    df = pd.DataFrame(
        {
            "timestamp_utc": idx,
            "chiller-status": 1.0,
            "outside-air-temp": oat_f,
        },
        index=idx,
    )
    return {"CHILLER_1": df}


def test_metric_bins_same_physical_hours():
    frames_f = _chiller_frame(oat_f=72.0)
    role_map = {
        "CHILLER_1": {
            "chiller-status": "chiller-status",
            "outside-air-temp": "outside-air-temp",
        }
    }
    imp = mech_cooling_oat_bins(
        frames_f, role_map, unit_system="imperial", prefer_web_oat=False
    )
    frames_c = _chiller_frame(oat_f=(72.0 - 32.0) * 5.0 / 9.0)
    met = mech_cooling_oat_bins(
        frames_c, role_map, unit_system="metric", prefer_web_oat=False
    )
    assert not imp.empty and not met.empty
    assert float(imp["runtime_hours"].sum()) == float(met["runtime_hours"].sum())
    assert set(imp["bin_start"]) == set(met["bin_start"])
    assert "70–75" in set(imp["bin_label"].astype(str))
    assert any("21" in str(x) for x in met["bin_label"])


def test_dump_tables_filenames(tmp_path: Path):
    idx = pd.date_range("2026-01-01", periods=4, freq="5min", tz="UTC")
    frames = {
        "VAV_1": pd.DataFrame(
            {"timestamp_utc": idx, "zone_t": 72.0, "zone_flow": 100.0},
            index=idx,
        )
    }
    written = dump_tables(tmp_path, frames=frames, role_map={}, building_id="B")
    for name in DUMP_FILENAMES:
        assert name in written
        assert written[name].is_file()
