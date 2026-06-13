from __future__ import annotations

import pyarrow as pa

from open_fdd.arrow_runtime.cookbook import flatline_1h_mask, flatline_window_samples, oob_mask, spread_1h_mask


def test_flatline_mask_flags_stable_series():
    table = pa.table({"timestamp": pa.array([1, 2, 3, 4]), "zone_temp": pa.array([70.0, 70.01, 70.0, 70.02])})
    mask = flatline_1h_mask(table, {"flatline_tolerance": 0.1, "flatline_window_samples": 3})
    assert mask.to_pylist()[-1] is True


def test_spread_mask_flags_jump():
    table = pa.table({"timestamp": pa.array([1, 2, 3, 4]), "zone_temp": pa.array([70.0, 71.0, 75.0, 80.0])})
    mask = spread_1h_mask(table, {"max_spread": 4.0, "flatline_window_samples": 3})
    assert mask.to_pylist()[-1] is True


def test_flatline_window_from_60s_poll():
    assert flatline_window_samples({"poll_interval_s": 60, "flatline_minutes": 60}) == 60


def test_flatline_window_prefers_poll_over_catalog_samples():
    assert flatline_window_samples({"poll_interval_s": 60, "window_samples": 12}) == 60


def test_oob_mask_flags_high():
    table = pa.table({"timestamp": pa.array([1, 2, 3]), "zone_temp": pa.array([70.0, 90.0, 72.0])})
    mask = oob_mask(table, {"bounds_low": 65, "bounds_high": 85, "rolling_avg_minutes": 1})
    assert True in mask.to_pylist()


def test_pid_hunting_command_flags_oscillation():
    from open_fdd.arrow_runtime.cookbook import pid_hunting_command_mask

    # Alternating 10/70 % command → many significant steps in 1 h window
    vals = []
    for i in range(70):
        vals.append(10.0 if i % 2 == 0 else 70.0)
    table = pa.table({"timestamp": pa.array(range(len(vals))), "damper_cmd": pa.array(vals)})
    mask = pid_hunting_command_mask(
        table,
        {
            "column": "damper_cmd",
            "hunting_window_samples": 60,
            "delta_os_max": 8,
            "min_command_delta": 0.05,
            "min_active_command": 0.05,
        },
    )
    assert mask.to_pylist()[-1] is True
