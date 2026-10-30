"""W5c: Overview processing uses SI storage; display preference is presentation-only."""

from __future__ import annotations

import pandas as pd
import pytest

from open_fdd.analytics.core import mech_cooling_oat_bins
from open_fdd.analytics.report_storage import STORAGE_ABI_METRIC, ensure_storage_frame, frame_for_display
from open_fdd.reporting.overview_export import build_overview_context
from open_fdd.rules import run_rule
from open_fdd.units.convert import PA_PER_IN_WC, fahrenheit_to_celsius


def _chiller_mechanical_cooling_frames() -> tuple[dict, dict]:
    idx = pd.date_range("2026-06-01", periods=48, freq="h", tz="UTC")
    oat_c = fahrenheit_to_celsius(75.0)
    frames = {
        "CHW_1": pd.DataFrame(
            {
                "outside-air-temp": [oat_c] * len(idx),
                "chiller-status": [1.0] * len(idx),
            },
            index=idx,
        )
    }
    frames["CHW_1"].attrs["storage_abi"] = STORAGE_ABI_METRIC
    role_map = {"CHW_1": {"equipType": "chwPlant"}}
    return frames, role_map


def test_overview_processing_invariant_to_display_preference():
    frames, role_map = _chiller_mechanical_cooling_frames()
    chw_leave = 8.8888888889

    bins_imperial_display = mech_cooling_oat_bins(
        frames,
        role_map,
        prefer_web_oat=False,
        chw_leave_max_f=chw_leave,
        use_status_proof=True,
        unit_system="metric",
    )
    ctx_imperial = build_overview_context(
        frames=frames,
        role_map=role_map,
        chw_leave_max=chw_leave,
        prefer_web_oat=False,
    )
    ctx_metric = build_overview_context(
        frames=frames,
        role_map=role_map,
        chw_leave_max=chw_leave,
        prefer_web_oat=False,
    )
    bins_from_ctx_imperial = mech_cooling_oat_bins(
        ctx_imperial["frames"],
        ctx_imperial["role_map"],
        prefer_web_oat=False,
        chw_leave_max_f=ctx_imperial["chw_leave_max"],
        use_status_proof=True,
        unit_system="metric",
    )
    bins_from_ctx_metric = mech_cooling_oat_bins(
        ctx_metric["frames"],
        ctx_metric["role_map"],
        prefer_web_oat=False,
        chw_leave_max_f=ctx_metric["chw_leave_max"],
        use_status_proof=True,
        unit_system="metric",
    )
    pd.testing.assert_frame_equal(bins_imperial_display, bins_from_ctx_imperial)
    pd.testing.assert_frame_equal(bins_imperial_display, bins_from_ctx_metric)

    idx = pd.date_range("2026-01-05T12:00:00Z", periods=12, freq="5min", tz="UTC")
    raw = pd.DataFrame(
        {
            "duct-static-pressure": [0.05] * len(idx),
            "duct-static-pressure-sp": [0.25] * len(idx),
            "fan-cmd": [1.0] * len(idx),
        },
        index=idx,
    )
    storage = ensure_storage_frame(
        raw,
        {
            "storage_abi": STORAGE_ABI_METRIC,
            "source_units": "imperial",
            "display_units": "imperial",
        },
    )
    storage.attrs["equipment_type"] = "ahu"
    fault_imperial = run_rule(
        "FC1",
        storage,
        params={"eps_dsp": 29.8608},
        poll_seconds=300,
        require_operational_gates=False,
    )
    storage_metric_display = ensure_storage_frame(
        raw,
        {
            "storage_abi": STORAGE_ABI_METRIC,
            "source_units": "imperial",
            "display_units": "si",
        },
    )
    storage_metric_display.attrs["equipment_type"] = "ahu"
    fault_metric = run_rule(
        "FC1",
        storage_metric_display,
        params={"eps_dsp": 29.8608},
        poll_seconds=300,
        require_operational_gates=False,
    )
    assert fault_imperial.fault_hours == pytest.approx(fault_metric.fault_hours, abs=0.01)

    presentation_imperial = frame_for_display(storage, "imperial")
    presentation_si = frame_for_display(storage, "si")
    pa_storage = float(storage["duct-static-pressure"].iloc[0])
    assert float(presentation_imperial["duct-static-pressure"].iloc[0]) == pytest.approx(
        pa_storage / PA_PER_IN_WC,
        rel=0.001,
    )
    assert float(presentation_si["duct-static-pressure"].iloc[0]) == pytest.approx(pa_storage, rel=0.001)