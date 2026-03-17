"""Tests for canonical FDD schema."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from open_fdd.schema import (
    FDDResult,
    FDDEvent,
    fdd_result_to_row,
    fdd_event_to_row,
    results_from_runner_output,
    events_from_flag_series,
)


def test_fdd_result_to_row():
    r = FDDResult(
        ts=datetime(2024, 1, 15, 10, 0),
        site_id="site1",
        equipment_id="hp_1",
        fault_id="hp_discharge_cold_flag",
        flag_value=1,
        evidence={"sat": 70.0},
    )
    row = r.to_row()
    assert len(row) == 6
    assert row[0] == datetime(2024, 1, 15, 10, 0)
    assert row[2] == "hp_1"
    assert row[4] == 1


def test_fdd_event_to_row():
    e = FDDEvent(
        site_id="site1",
        equipment_id="hp_1",
        fault_id="hp_discharge_cold_flag",
        start_ts=datetime(2024, 1, 15, 10, 0),
        end_ts=datetime(2024, 1, 15, 11, 0),
        duration_seconds=3600,
    )
    row = e.to_row()
    assert len(row) == 7
    assert row[5] == 3600


def test_results_from_runner_output():
    df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2024-01-15 10:00", "2024-01-15 10:05"]),
            "hp_discharge_cold_flag": [0, 1],
            "bad_sensor_flag": [0, 0],
        }
    )
    results = results_from_runner_output(df, "site1", "hp_1")
    assert len(results) == 1
    assert results[0].fault_id == "hp_discharge_cold_flag"
    assert results[0].equipment_id == "hp_1"
    assert results[0].flag_value == 1


def test_events_from_flag_series():
    df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [
                    "2024-01-15 10:00",
                    "2024-01-15 10:05",
                    "2024-01-15 10:10",
                    "2024-01-15 10:15",
                    "2024-01-15 10:20",
                ]
            ),
            "hp_discharge_cold_flag": [0, 1, 1, 1, 0],
        }
    )
    events = events_from_flag_series(df, "hp_discharge_cold_flag", "site1", "hp_1")
    assert len(events) == 1
    assert events[0].fault_id == "hp_discharge_cold_flag"
    # 10:05 to 10:15 = 10 min = 600 sec
    assert events[0].duration_seconds == 600


def test_load_timeseries_for_equipment_uses_string_site_id(monkeypatch):
    """Regression: load_timeseries_for_equipment must not pass UUID objects to psycopg2."""
    from open_fdd.platform import loop

    calls: list[tuple[tuple, dict]] = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, _query, params=None):
            # Record params for assertion; simulate empty result.
            calls.append((params or (), {}))

        def fetchall(self):
            return []

    class FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return FakeCursor()

    with patch.object(loop, "get_conn", return_value=FakeConn()):
        df = loop.load_timeseries_for_equipment(
            site_id="c7c9dfb8-9c1f-4a1b-bf3f-9f3e5aa4f111",
            equipment_id="AHU-1",
            start_ts=datetime(2024, 1, 1),
            end_ts=datetime(2024, 1, 2),
            column_map={},
        )

    # No data is fine (we mocked fetchall to be empty), but the execute params
    # must all be plain strings, not uuid.UUID instances.
    assert df is None
    assert calls, "Expected at least one DB call"
    first_params = calls[0][0]
    assert all(not hasattr(p, "hex") for p in first_params), "UUID objects should not be passed to psycopg2"
