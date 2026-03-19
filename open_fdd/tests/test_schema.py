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
        def __init__(self, which_cursor: int):
            self._which_cursor = which_cursor

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, _query, params=None):
            calls.append((params or (), {}))

        def fetchall(self):
            # Cursor 0: points query → one row so second get_conn/execute runs.
            # Cursor 1: timeseries query → row with ts/external_id/value so pivot_table succeeds.
            if self._which_cursor == 0:
                return [{"id": "11111111-1111-1111-1111-111111111111", "external_id": "p1"}]
            return [
                {
                    "ts": datetime(2024, 1, 1, 0, 0),
                    "external_id": "p1",
                    "value": 1.0,
                }
            ]

    class FakeConn:
        def __init__(self):
            self._cursor_calls = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            c = FakeCursor(self._cursor_calls)
            self._cursor_calls += 1
            return c

    with patch.object(loop, "get_conn", return_value=FakeConn()):
        df = loop.load_timeseries_for_equipment(
            site_id="c7c9dfb8-9c1f-4a1b-bf3f-9f3e5aa4f111",
            equipment_id="AHU-1",
            start_ts=datetime(2024, 1, 1),
            end_ts=datetime(2024, 1, 2),
            column_map={},
        )

    # We don't care about df shape here, only that both queries ran with non-UUID params.
    assert len(calls) >= 2, "Expected both points and timeseries query"
    first_params = calls[0][0]
    assert all(not hasattr(p, "hex") for p in first_params), "UUID objects should not be passed to psycopg2"
    second_params = calls[1][0]
    assert all(not hasattr(p, "hex") for p in second_params), "UUID objects should not be passed to psycopg2"
