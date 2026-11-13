"""Qualification tests for pandas SV-RATE (open_fdd.rules.sensor_rate) and retained divergence policy."""
from __future__ import annotations

import numpy as np
import pandas as pd

from open_fdd.parity.policy import expected_deltas, known_differences
from open_fdd.rules.sensor_rate import (
    detect_operating_state,
    evaluate_point,
    sv_rate_compute,
)
from open_fdd.rules.sensor_rate_profiles import resolve_profile


def _series_df(minutes: list[int], values: list[float], *, role: str = "discharge-air-temp",
               fan: list[int] | None = None) -> pd.DataFrame:
    idx = pd.Timestamp("2026-01-05T00:00:00Z") + pd.to_timedelta(minutes, unit="m")
    data = {role: values}
    if fan is not None:
        data["fan-status"] = fan
    df = pd.DataFrame(data, index=idx)
    df.attrs["equipment_id"] = "AHU-QUAL"
    df.attrs["role_units"] = {role: "°C"}
    return df


def test_sv_rate_irregular_cadence_scales_deadband_and_ignores_normal_drift():
    # Mixed 2-min, 7-min, 15-min steps with gentle 0.1 C/step drift (< steady limit 8.8889 C/h).
    minutes = [0, 2, 9, 16, 31, 33, 40, 55, 70]
    values = [20.0 + 0.1 * i for i in range(len(minutes))]
    df = _series_df(minutes, values, fan=[1] * len(minutes))
    mask = sv_rate_compute(df, {}, 300.0)
    assert not bool(mask.any())
    assert df.attrs["sv_rate_evidence"][0]["fault_hours_raw"] == 0.0


def test_sv_rate_gap_resets_rate_calculation_across_outage():
    # Value shifts by 15 C across a 180-minute (> max_gap_hours=2.0) gap; gap intervals must not fault.
    minutes = [0, 5, 10, 15, 195, 200, 205, 210]
    values = [20.0, 20.0, 20.0, 20.0, 35.0, 35.0, 35.0, 35.0]
    df = _series_df(minutes, values, fan=[1] * len(minutes))
    mask = sv_rate_compute(df, {}, 300.0)
    assert not bool(mask.any())
    assert df.attrs["sv_rate_evidence"][0]["fault_hours_raw"] == 0.0


def test_sv_rate_profiles_differ_between_zone_and_discharge_air_temp():
    # Same ramp (0.5 C per 5 min = 6.0 C/h): zone-air-temp steady limit (3.3333 C/h) faults when sustained,
    # whereas discharge-air-temp steady limit (8.8889 C/h) stays well within bounds.
    minutes = [m for m in range(0, 120, 5)]
    values = [21.0 + (0.5 * (i - 5) if i >= 6 else 0.0) for i in range(len(minutes))]
    df_sat = _series_df(minutes, values, role="discharge-air-temp", fan=[1] * len(minutes))
    df_zone = _series_df(minutes, values, role="zone-air-temp", fan=[1] * len(minutes))
    assert not bool(sv_rate_compute(df_sat, {}, 300.0).any())
    zone_mask = sv_rate_compute(df_zone, {}, 300.0)
    assert bool(zone_mask.any())
    assert df_zone.attrs["sv_rate_evidence"][0]["fault_hours_raw"] > 0.0


def test_sv_rate_persistence_rejects_single_isolated_jump_when_below_confirm_window():
    # Single step jump of +1.5 C (below extreme_interval_change) that returns right back stays unconfirmed.
    minutes = [m for m in range(0, 90, 5)]
    values = [20.0] * len(minutes)
    values[8] = 21.5
    df = _series_df(minutes, values, role="zone-air-temp", fan=[1] * len(minutes))
    mask = sv_rate_compute(df, {"persistence_min": 20.0}, 300.0)
    assert not bool(mask.any())


def test_sv_rate_same_role_peers_evaluate_independently_without_contamination():
    minutes = [m for m in range(0, 90, 5)]
    healthy_vals = [21.0 + 0.05 * (i % 2) for i in range(len(minutes))]
    fault_vals = [21.0 + (2.0 * (i - 5) if 6 <= i <= 11 else 0.0) for i in range(len(minutes))]
    df_h = _series_df(minutes, healthy_vals, fan=[1] * len(minutes))
    df_f = _series_df(minutes, fault_vals, fan=[1] * len(minutes))
    prof, _ = resolve_profile(role="discharge-air-temp")
    assert prof is not None
    state_h, _ = detect_operating_state(df_h)
    state_f, _ = detect_operating_state(df_f)
    ev_h = evaluate_point(df_h["discharge-air-temp"], state_h, prof)
    ev_f = evaluate_point(df_f["discharge-air-temp"], state_f, prof)
    assert not bool(ev_h["fault_mask"].any())
    assert bool(ev_f["fault_mask"].any())

    nan_df = df_h.copy()
    nan_df["discharge-air-temp"] = np.nan
    assert not bool(sv_rate_compute(nan_df, {}, 300.0).any())


def test_sv_rate_known_divergence_remains_explicitly_documented_and_pinned():
    assert "SV-RATE" in known_differences("all")
    assert "SV-RATE" in expected_deltas("basic/0/8/7")
