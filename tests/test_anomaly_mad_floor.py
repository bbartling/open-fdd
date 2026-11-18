"""MAD floor and near-constant skip (#1657)."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from open_fdd.analytics.anomaly.detectors import anomaly_minutes, is_near_constant, resolution, rolling_mad_flags

IDX = pd.date_range("2026-01-05", periods=7 * 288, freq="5min", tz="UTC")


def quantized_damper(seed=0):
    """A week of a damper that only moves between 88.67 % and 88.80 % in 0.006 % steps (the issue's signal)."""
    rng = np.random.default_rng(seed)
    steps = np.cumsum(rng.choice([-1, 0, 0, 0, 1], size=len(IDX)))
    level = 88.67 + 0.006 * np.mod(steps, 22)
    return pd.Series(np.round(level, 3), index=IDX)


def test_resolution_and_near_constant():
    damper = quantized_damper()
    assert resolution(damper) == pytest.approx(0.006, abs=0.0015)
    assert is_near_constant(damper)
    noisy = pd.Series(13 + np.random.default_rng(1).normal(0, 0.3, len(IDX)), index=IDX)
    assert not is_near_constant(noisy)


def test_mad_ignores_resolution_steps_but_keeps_real_outliers():
    damper = quantized_damper()
    assert anomaly_minutes(rolling_mad_flags(damper, window=288), pd.Timedelta(minutes=5)) == 0.0
    noisy = pd.Series(13 + np.random.default_rng(1).normal(0, 0.3, len(IDX)), index=IDX)
    noisy.iloc[1000] = 25.0
    flags = rolling_mad_flags(noisy, window=288)
    assert bool(flags.iloc[1000])
    flat = pd.Series(5.0, index=IDX)
    flat.iloc[900] = 6.0
    assert not rolling_mad_flags(flat, window=288).any()  # MAD == 0 still never flags


def test_screen_skips_a_near_constant_point(tmp_path):
    pytest.importorskip("matplotlib")
    from open_fdd.analytics.anomaly.screen import screen_folder

    folder = tmp_path / "AHU_1"
    folder.mkdir()
    pd.DataFrame(
        {"timestamp_utc": IDX.strftime("%Y-%m-%dT%H:%M:%SZ"), "DMPR": quantized_damper().to_numpy(), "FAN": 1.0}
    ).to_csv(folder / "history_wide.csv", index=False)
    (folder / "column_map.json").write_text(
        json.dumps({"equipType": "AHU", "points": {"oa_damper_pct": "DMPR", "fan_status": "FAN"}}), encoding="utf-8"
    )
    res = screen_folder(folder, tmp_path / "s", methods=["zscore", "mad"], top_n=0, max_days=0, plots=False)
    row = res.scoreboard[res.scoreboard["point"] == "DMPR"].iloc[0]
    assert row["skipped_reason"] == "near_constant" and row["anomaly_minutes"] == 0.0


@pytest.mark.parametrize("samples", [5, 15])
def test_short_excursion_on_a_near_constant_signal_is_not_skipped(samples):
    """A flat damper that drops to 0 for a few samples (under 1 % of rows) is still screened, and MAD flags it."""
    damper = quantized_damper()
    damper.iloc[1000 : 1000 + samples] = 0.0
    assert not is_near_constant(damper)
    flags = rolling_mad_flags(damper, window=288)
    assert flags.iloc[1000 : 1000 + samples].any()


def test_zero_median_valve_spike_is_not_skipped():
    """A closed valve that reads 0.0-0.3 % in 0.1 % steps and opens to 100 % for 10 samples is still screened."""
    rng = np.random.default_rng(3)
    valve = pd.Series(rng.choice([0.0, 0.0, 0.0, 0.1, 0.2, 0.3], size=len(IDX)), index=IDX)
    valve.iloc[1200:1210] = 100.0
    assert not is_near_constant(valve)


def test_screen_keeps_a_short_excursion_on_a_flat_point(tmp_path):
    pytest.importorskip("matplotlib")
    from open_fdd.analytics.anomaly.screen import screen_folder

    damper = quantized_damper()
    damper.iloc[1000:1015] = 0.0
    folder = tmp_path / "AHU_1"
    folder.mkdir()
    pd.DataFrame(
        {"timestamp_utc": IDX.strftime("%Y-%m-%dT%H:%M:%SZ"), "DMPR": damper.to_numpy(), "FAN": 1.0}
    ).to_csv(folder / "history_wide.csv", index=False)
    (folder / "column_map.json").write_text(
        json.dumps({"equipType": "AHU", "points": {"oa_damper_pct": "DMPR", "fan_status": "FAN"}}), encoding="utf-8"
    )
    res = screen_folder(folder, tmp_path / "s", methods=["mad"], top_n=0, max_days=0, plots=False)
    rows = res.scoreboard[res.scoreboard["point"] == "DMPR"]
    assert (rows["skipped_reason"].fillna("") != "near_constant").all()
    assert rows["anomaly_minutes"].max() > 0.0
