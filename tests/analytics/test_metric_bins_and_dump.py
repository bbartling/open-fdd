"""Pandas analytics metric OAT bins and dump_tables contract."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from open_fdd.analytics import DUMP_FILENAMES, dump_tables, mech_cooling_oat_bins
from open_fdd.analytics.report_storage import STORAGE_ABI_METRIC
from open_fdd.analytics.units import stamp_display_units
from open_fdd.units.convert import fahrenheit_to_celsius


def _chiller_frame(*, oat_c: float) -> dict:
    idx = pd.date_range("2026-01-01", periods=12, freq="5min", tz="UTC")
    df = pd.DataFrame(
        {
            "chiller-status": 1.0,
            "outside-air-temp": oat_c,
        },
        index=idx,
    )
    df.attrs["storage_abi"] = STORAGE_ABI_METRIC
    df.attrs["role_units"] = {"outside-air-temp": "°C", "chiller-status": "bool"}
    stamp_display_units(df, {"display_units": "si"})
    return {"CHILLER_1": df}


def test_metric_bins_same_physical_hours():
    oat_c = fahrenheit_to_celsius(72.0)
    frames = _chiller_frame(oat_c=oat_c)
    role_map = {
        "CHILLER_1": {
            "equipType": "chiller",
            "chiller-status": "chiller-status",
            "outside-air-temp": "outside-air-temp",
        }
    }
    met = mech_cooling_oat_bins(frames, role_map, prefer_web_oat=False, unit_system="metric")
    assert not met.empty
    assert float(met["hours"].sum()) > 0
    labels = set(met["bin_label"].astype(str))
    assert any("21" in label or "22" in label for label in labels)


def test_dump_tables_filenames(tmp_path: Path):
    idx = pd.date_range("2026-01-01", periods=4, freq="5min", tz="UTC")
    frames = {
        "VAV_1": pd.DataFrame(
            {"zone-air-temp": [fahrenheit_to_celsius(72.0)] * len(idx)},
            index=idx,
        )
    }
    written = dump_tables(tmp_path, frames=frames, role_map={}, building_id="B")
    for name in DUMP_FILENAMES:
        assert name in written
        assert written[name].is_file()
