from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[2]
API_ROOT = REPO / "workspace" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from openfdd_bridge.fdd_row_prep import (  # noqa: E402
    ROLLING_AVG_MINUTES_ALLOWED,
    attach_rolling_avg,
    aux_series_key,
    build_rolling_aux_series,
    normalize_rolling_avg_minutes,
    prepare_fdd_rows,
    rolling_avg_values_for_column,
)


def _temp_rows(n: int = 20, *, step_min: int = 1) -> list[dict]:
    end = pd.Timestamp.now(tz="UTC").floor("min")
    ts = pd.date_range(end - pd.Timedelta(minutes=(n - 1) * step_min), periods=n, freq=f"{step_min}min", tz="UTC")
    rows = []
    for i, t in enumerate(ts):
        rows.append(
            {
                "ts_ms": int(t.value // 1_000_000),
                "temp": float(70 + i),
                "degF": float(70 + i),
            }
        )
    return rows


def test_normalize_rolling_avg_minutes():
    assert normalize_rolling_avg_minutes(5) == 5
    assert normalize_rolling_avg_minutes(15) == 15
    assert normalize_rolling_avg_minutes(7) in ROLLING_AVG_MINUTES_ALLOWED
    assert normalize_rolling_avg_minutes("bad") == 5


def test_attach_rolling_avg_5min_window():
    rows = _temp_rows(30, step_min=1)
    attach_rolling_avg(rows, minutes=5)
    last = rows[-1]
    assert last["rolling_avg_minutes"] == 5
    assert last["samples_in_avg"] >= 5
    cutoff = last["ts_ms"] - 5 * 60_000
    in_window = [r["temp"] for r in rows if r["ts_ms"] >= cutoff]
    assert last["temp_rolling_avg"] == pytest.approx(sum(in_window) / len(in_window))


def test_rolling_avg_values_for_column_aligned():
    rows = _temp_rows(12, step_min=1)
    df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime([r["ts_ms"] for r in rows], unit="ms", utc=True),
            "oa-t": [r["temp"] for r in rows],
        }
    )
    avg = rolling_avg_values_for_column(df, "oa-t", minutes=5)
    assert len(avg) == len(df)
    cutoff = rows[-1]["ts_ms"] - 5 * 60_000
    in_window = [r["temp"] for r in rows if r["ts_ms"] >= cutoff]
    assert avg[-1] == pytest.approx(sum(in_window) / len(in_window))


def test_build_rolling_aux_series_skips_humidity():
    df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime([1700000000000, 1700000060000], unit="ms", utc=True),
            "oa-t": [70.0, 71.0],
            "oa-h": [50.0, 51.0],
        }
    )
    aux = build_rolling_aux_series(df, ["oa-t", "oa-h"], {"oa-t": "temperature", "oa-h": "humidity"}, minutes=5)
    assert aux_series_key("oa-t", 5) in aux
    assert aux_series_key("oa-h", 5) not in aux


def test_prepare_fdd_rows_injects_temp_rolling_avg():
    end = pd.Timestamp.now(tz="UTC").floor("min")
    ts = pd.date_range(end - pd.Timedelta(minutes=9), periods=10, freq="1min", tz="UTC")
    df = pd.DataFrame({"timestamp": ts, "oa-t": [float(70 + i) for i in range(10)]})
    model = {
        "points": [
            {
                "id": "p1",
                "site_id": "demo",
                "brick_type": "Zone_Air_Temperature_Sensor",
                "external_id": "oa-t",
            }
        ]
    }
    rule = {"config": {"rolling_avg_minutes": 5}, "bindings": {"point_ids": ["p1"]}}
    rows = prepare_fdd_rows(df, rule, model, "demo")
    assert rows
    assert "temp_rolling_avg" in rows[-1]
    assert rows[-1]["rolling_avg_minutes"] == 5
