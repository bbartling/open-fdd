"""Regression: load_timeseries_for_equipment must not pass UUID objects to psycopg2."""

from datetime import datetime
from unittest.mock import patch

import openfdd_stack.platform.loop as loop


def test_load_timeseries_for_equipment_uses_string_site_id():
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
        loop.load_timeseries_for_equipment(
            site_id="c7c9dfb8-9c1f-4a1b-bf3f-9f3e5aa4f111",
            equipment_id="AHU-1",
            start_ts=datetime(2024, 1, 1),
            end_ts=datetime(2024, 1, 2),
            column_map={},
        )

    assert len(calls) >= 2, "Expected both points and timeseries query"
    first_params = calls[0][0]
    assert all(not hasattr(p, "hex") for p in first_params), "UUID objects should not be passed to psycopg2"
    second_params = calls[1][0]
    assert all(not hasattr(p, "hex") for p in second_params), "UUID objects should not be passed to psycopg2"
