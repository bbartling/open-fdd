"""VAV-1 comfort band follows the occupancy schedule; VAV-2 keeps unoccupied setback."""

from __future__ import annotations

import pandas as pd

from open_fdd.analytics.occupancy import OccupancySchedule
from open_fdd.rules.cookbook_catalog import vav1, vav2


def _frame(temps, occupied=None):
    idx = pd.date_range("2026-01-05 12:00", periods=len(temps), freq="h", tz="UTC")
    data = {"zone-air-temp": temps}
    if occupied is not None:
        data["occupied"] = occupied
    return pd.DataFrame(data, index=idx)


def test_vav1_faults_occupied_band_and_skips_unoccupied():
    df = _frame(
        [80.0, 80.0, 72.0, 60.0, 85.0, 85.0],
        ["occupied", "unoccupied", "occupied", "occupied", "0.03", "1.0"],
    )
    raw = vav1(df, {}, 300.0)
    assert list(raw.fillna(False)) == [True, False, False, True, False, True]


def test_vav1_without_occupancy_evaluates_every_sample():
    df = _frame([80.0, 60.0, 72.0])
    raw = vav1(df, {}, 300.0)
    assert list(raw.fillna(False)) == [True, True, False]


def test_vav1_require_occupied_off_includes_unoccupied():
    df = _frame([80.0, 80.0], ["occupied", "unoccupied"])
    raw = vav1(df, {"require_occupied": 0}, 300.0)
    assert list(raw.fillna(False)) == [True, True]


def test_vav1_overview_calendar_gates_when_occ_column_absent():
    # Monday 2026-01-05. Default calendar is occupied 06:00–18:00 local.
    idx = pd.date_range("2026-01-05 02:00", periods=2, freq="8h", tz="America/Chicago")
    df = pd.DataFrame({"zone-air-temp": [80.0, 80.0]}, index=idx)
    raw = vav1(df, {"occupancy_schedule": OccupancySchedule().to_dict()}, 300.0)
    assert list(raw.fillna(False)) == [False, True]


def test_unoccupied_setback_stays_on_vav2():
    df = _frame([80.0, 80.0], ["occupied", "unoccupied"])
    assert list(vav1(df, {}, 300.0).fillna(False)) == [True, False]
    assert list(vav2(df, {"setback_hi": 68.0}, 300.0).fillna(False)) == [False, True]
