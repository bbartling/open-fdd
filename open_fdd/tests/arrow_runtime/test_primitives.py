"""Arrow rule primitives — synthetic table tests."""

from __future__ import annotations

import pyarrow as pa

from open_fdd.arrow_runtime.primitives import (
    command_feedback_mismatch,
    persistence_mask,
    simultaneous_heat_cool_mask,
    threshold_mask,
)


def test_threshold_mask_gt():
    table = pa.table({"zone_temp": [70.0, 80.0, 90.0]})
    mask = threshold_mask(table, {"threshold": 75.0, "column": "zone_temp"}, op="gt")
    assert mask.to_pylist() == [False, True, True]


def test_simultaneous_heat_cool():
    table = pa.table({"heat": [0.0, 0.5, 0.0], "cool": [0.0, 0.6, 0.2]})
    mask = simultaneous_heat_cool_mask(table, {"valve_on_min": 0.1}, heat_col="heat", cool_col="cool")
    assert mask.to_pylist()[1] is True
    assert mask.to_pylist()[0] is False


def test_command_feedback_mismatch():
    table = pa.table({"cmd": [50.0, 50.0], "fb": [50.0, 40.0]})
    mask = command_feedback_mismatch(
        table, {"cmd_fb_tolerance": 5.0}, command_col="cmd", feedback_col="fb"
    )
    assert mask.to_pylist() == [False, True]


def test_persistence_mask():
    mask = pa.array([False, True, True, True, False])
    out = persistence_mask(mask, 3)
    assert out.to_pylist()[3] is True
