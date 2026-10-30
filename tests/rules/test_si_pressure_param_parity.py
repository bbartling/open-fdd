"""SI Pa rule params vs legacy imperial wide storage (frozen IP path)."""

from __future__ import annotations

import pandas as pd
import pytest

from open_fdd.analytics.report_storage import STORAGE_ABI_METRIC, ensure_storage_frame, oracle_seed_frame_from_imperial_wide
from open_fdd.rules import run_rule
from open_fdd.units.convert import PA_PER_IN_WC


def _fc1_fault_frame_imperial_wide() -> pd.DataFrame:
    idx = pd.date_range("2026-01-05T12:00:00Z", periods=24, freq="5min", tz="UTC")
    return pd.DataFrame(
        {
            "duct-static-pressure": [0.05] * len(idx),
            "duct-static-pressure-sp": [0.25] * len(idx),
            "fan-cmd": [1.0] * len(idx),
            "fan-status": [1] * len(idx),
        },
        index=idx,
    )


def test_fc1_si_pa_threshold_matches_imperial_inwc_on_same_physics():
    imperial = _fc1_fault_frame_imperial_wide()
    imperial.attrs["equipment_type"] = "ahu"
    imperial_ip = imperial.copy()
    imperial_ip.attrs = dict(imperial.attrs)
    ip_result = run_rule(
        "FC1",
        imperial_ip,
        params={"eps_dsp": 0.12},
        poll_seconds=300,
        require_operational_gates=False,
    )

    si = oracle_seed_frame_from_imperial_wide(imperial)
    si.attrs["equipment_type"] = "ahu"
    si_result = run_rule(
        "FC1",
        si,
        params={"eps_dsp": 0.12 * PA_PER_IN_WC},
        poll_seconds=300,
        require_operational_gates=False,
    )

    assert ip_result.fault_hours == pytest.approx(si_result.fault_hours, abs=0.05)
    assert (ip_result.fault_hours or 0) > 0


def test_ahu_ducthi_si_pa_margin_matches_imperial_inwc():
    idx = pd.date_range("2026-01-05T12:00:00Z", periods=24, freq="5min", tz="UTC")
    imperial = pd.DataFrame(
        {
            "duct-static-pressure": [1.50] * len(idx),
            "duct-static-pressure-sp": [1.2] * len(idx),
            "fan-status": [1] * len(idx),
            "fan-cmd": [1] * len(idx),
        },
        index=idx,
    )
    imperial.attrs["equipment_type"] = "ahu"
    ip = run_rule(
        "AHU-DUCTHI",
        imperial.copy(),
        params={"duct_high_margin": 0.25},
        poll_seconds=300,
    )

    si = oracle_seed_frame_from_imperial_wide(imperial)
    si.attrs["equipment_type"] = "ahu"
    metric = run_rule(
        "AHU-DUCTHI",
        si,
        params={"duct_high_margin": 0.25 * PA_PER_IN_WC},
        poll_seconds=300,
    )
    assert ip.fault_hours == pytest.approx(metric.fault_hours, abs=0.05)


def test_ensure_storage_frame_uses_source_units_not_display():
    idx = pd.date_range("2026-01-01", periods=1, freq="h", tz="UTC")
    raw = pd.DataFrame({"outside-air-temp": [68.0]}, index=idx)
    display_only = ensure_storage_frame(
        raw.copy(),
        {"storage_abi": STORAGE_ABI_METRIC, "display_units": "imperial"},
    )
    assert float(display_only["outside-air-temp"].iloc[0]) == pytest.approx(68.0)

    converted = ensure_storage_frame(
        raw.copy(),
        {
            "storage_abi": STORAGE_ABI_METRIC,
            "source_units": "imperial",
            "display_units": "si",
        },
    )
    assert float(converted["outside-air-temp"].iloc[0]) == pytest.approx(20.0, abs=0.05)
