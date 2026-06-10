from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import datetime as dt

import pyarrow as pa

REPO = Path(__file__).resolve().parents[2]
RULES = REPO / "workspace" / "data" / "rules_py"


def _load_rule(name: str):
    path = RULES / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _ts(n: int):
    base = dt.datetime(2026, 1, 15, 10, 0, tzinfo=dt.timezone.utc)
    return pa.array([base + dt.timedelta(minutes=i) for i in range(n)], type=pa.timestamp("us", tz="UTC"))


def test_vav_airflow_low_norm_cmd_percent():
    mod = _load_rule("vav_airflow_low.py")
    table = pa.table(
        {
            "timestamp": _ts(3),
            "airflow": [30.0, 30.0, 30.0],
            "damper-position-command": [50.0, 50.0, 50.0],
        }
    )
    mask = mod.apply_faults_arrow(table, {"value_column": "airflow"})
    assert mask.to_pylist() == [True, True, True]


def test_vav_airflow_low_norm_cmd_fraction():
    mod = _load_rule("vav_airflow_low.py")
    table = pa.table(
        {
            "timestamp": _ts(3),
            "airflow": [30.0, 80.0, 30.0],
            "damper-position-command": [0.5, 0.5, 0.05],
        }
    )
    mask = mod.apply_faults_arrow(table, {"value_column": "airflow"})
    assert mask.to_pylist() == [True, False, False]


def test_vav_airflow_missing_column_returns_false():
    mod = _load_rule("vav_airflow_low.py")
    table = pa.table({"timestamp": _ts(2), "other": [1.0, 2.0]})
    mask = mod.apply_faults_arrow(table, {"value_column": "airflow"})
    assert mask.to_pylist() == [False, False]


def test_zone_reheat_warm_ambient_missing_oat():
    mod = _load_rule("zone_reheat_warm_ambient.py")
    table = pa.table({"timestamp": _ts(2), "heating-valve-command": [0.8, 0.8]})
    mask = mod.apply_faults_arrow(table, {"reheat_column": "heating-valve-command"})
    assert mask.to_pylist() == [False, False]


def test_zone_reheat_warm_ambient_flags_warm_reheat():
    mod = _load_rule("zone_reheat_warm_ambient.py")
    table = pa.table(
        {
            "timestamp": _ts(2),
            "oa-t": [80.0, 70.0],
            "heating-valve-command": [60.0, 60.0],
        }
    )
    mask = mod.apply_faults_arrow(table, {})
    assert mask.to_pylist() == [True, False]


def test_vav_zone_bounds_occupied_gates_unoccupied():
    mod = _load_rule("vav_zone_temp_bounds_occupied.py")
    table = pa.table({"timestamp": _ts(4), "zone_temp": [90.0, 90.0, 90.0, 90.0]})
    cfg = {
        "value_column": "zone_temp",
        "bounds_low": 65,
        "bounds_high": 78,
        "occupied_start_hour": 8,
        "occupied_end_hour": 17,
        "tz_offset_hours": 0,
        "rolling_avg_minutes": 1,
    }
    mask = mod.apply_faults_arrow(table, cfg)
    assert len(mask) == 4
    assert True in mask.to_pylist()


def test_oat_vs_web_spread_flags_divergence():
    mod = _load_rule("oat_vs_web_spread_1h.py")
    table = pa.table(
        {
            "timestamp": _ts(3),
            "oa-t": [70.0, 70.0, 90.0],
            "web-oat-t": [71.0, 72.0, 70.0],
        }
    )
    mask = mod.apply_faults_arrow(table, {})
    assert mask.to_pylist() == [False, False, True]


def test_oat_vs_web_spread_missing_column_safe():
    mod = _load_rule("oat_vs_web_spread_1h.py")
    table = pa.table({"timestamp": _ts(2), "oa-t": [70.0, 71.0]})
    mask = mod.apply_faults_arrow(table, {})
    assert mask.to_pylist() == [False, False]


def test_flatline_1h_occupied_only_flag():
    mod = _load_rule("flatline_1h.py")
    table = pa.table({"timestamp": _ts(4), "zone_temp": [70.0, 70.0, 70.0, 70.0]})
    mask = mod.apply_faults_arrow(
        table,
        {
            "value_column": "zone_temp",
            "flatline_window_samples": 3,
            "flatline_tolerance": 0.1,
            "occupied_only": True,
            "occupied_start_hour": 8,
            "occupied_end_hour": 17,
            "tz_offset_hours": 0,
        },
    )
    assert len(mask) == 4
