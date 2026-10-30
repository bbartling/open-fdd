"""T1407-1: VAV-1 occupancy gate and comfort band units."""

from __future__ import annotations

import unittest

import pandas as pd

from open_fdd.analytics.occupancy import OccupancySchedule
from open_fdd.rules.cookbook_catalog import vav1, vav1_occupied_mask
from open_fdd.rules.runner import RULES, run_cookbook_rule


def _frame(temps, *, unit="degF", occupied=None):
    idx = pd.date_range("2026-01-05 12:00", periods=len(temps), freq="h", tz="UTC")
    data = {"zone-air-temp": temps}
    if occupied is not None:
        data["occupied"] = occupied
    df = pd.DataFrame(data, index=idx)
    df.attrs["role_units"] = {"zone-air-temp": unit}
    return df


def test_vav1_without_occupancy_is_not_assessed():
    df = _frame([80.0, 60.0, 72.0])
    mask, src = vav1_occupied_mask(df, {})
    assert src == "ungated_no_occ"
    assert not mask.any()
    raw = vav1(df, {}, 300.0)
    assert not raw.fillna(False).any()


def test_vav1_celsius_band_uses_declared_unit():
    df = _frame([22.0, 28.0], unit="degC", occupied=["occupied", "occupied"])
    params = {"zone_lo": 21.111111, "zone_hi": 23.888889}
    raw = vav1(df, params, 300.0)
    assert list(raw.fillna(False)) == [False, True]


def test_vav1_runner_not_assessed_no_occupancy():
    rule = next(r for r in RULES if r.id == "VAV-1")
    df = _frame([80.0, 80.0])
    result = run_cookbook_rule(
        rule,
        df,
        equipment_id="VAV_1",
        equipment_kind="vav",
        poll_seconds=300.0,
    )
    assert result.status == "NOT_ASSESSED_NO_OCCUPANCY"
    assert result.fault_hours == 0.0


def test_vav1_overview_calendar_still_evaluates():
    idx = pd.date_range("2026-01-05 02:00", periods=2, freq="8h", tz="America/Chicago")
    df = pd.DataFrame({"zone-air-temp": [22.0, 26.0]}, index=idx)
    df.attrs["role_units"] = {"zone-air-temp": "degC"}
    params = {"zone_lo": 21.111111, "zone_hi": 23.888889}
    raw = vav1(df, {**params, "occupancy_schedule": OccupancySchedule().to_dict()}, 300.0)
    assert list(raw.fillna(False)) == [False, True]


class TestVav1T1407(unittest.TestCase):
    test_vav1_without_occupancy_is_not_assessed = staticmethod(
        test_vav1_without_occupancy_is_not_assessed
    )
    test_vav1_celsius_band_uses_declared_unit = staticmethod(
        test_vav1_celsius_band_uses_declared_unit
    )
    test_vav1_runner_not_assessed_no_occupancy = staticmethod(
        test_vav1_runner_not_assessed_no_occupancy
    )
    test_vav1_overview_calendar_still_evaluates = staticmethod(
        test_vav1_overview_calendar_still_evaluates
    )


if __name__ == "__main__":
    unittest.main()
