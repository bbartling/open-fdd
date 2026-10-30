"""W5c: offline Overview export processing stays on SI storage regardless of display preference."""

from __future__ import annotations

import pandas as pd
import pytest

from open_fdd.analytics.report_storage import STORAGE_ABI_METRIC, ensure_storage_frame, frame_for_display
from open_fdd.reporting.overview_export import build_overview_context


def test_overview_context_processing_inputs_stay_si_with_imperial_display_preference():
    idx = pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC")
    # Legacy wide CSV magnitudes are °F when display_units is imperial.
    raw = pd.DataFrame({"outside-air-temp": [68.0, 69.8, 71.6]}, index=idx)
    column_map = {"storage_abi": STORAGE_ABI_METRIC, "display_units": "imperial"}
    storage = ensure_storage_frame(raw, column_map)
    display = frame_for_display(storage, "imperial")
    assert float(display["outside-air-temp"].iloc[0]) == pytest.approx(68.0, abs=0.01)

    ctx = build_overview_context(
        frames={"AHU_1": storage},
        role_map={"AHU_1": {"equipType": "ahu"}},
        oat_err=5.0,
        zone_lo=21.111111,
        zone_hi=23.888889,
        chw_leave_max=8.8888888889,
    )
    assert ctx["oat_err"] == 5.0
    assert ctx["zone_lo"] == pytest.approx(21.111111)
    assert ctx["chw_leave_max"] == pytest.approx(8.8888888889)
    proc = ctx["frames"]["AHU_1"]
    assert float(proc["outside-air-temp"].iloc[0]) == pytest.approx(20.0, abs=0.05)
