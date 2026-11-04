"""T1404 pandas twin: as-of web alignment and primary-reference selection."""

from __future__ import annotations

import pandas as pd

from open_fdd.rules.base import confirm_fault, hours_true
from open_fdd.rules.cookbook_catalog import oat_vs_meteo
from open_fdd.rules.runner import merge_weather


def _frame(local_offset_f: float, hours: int = 2) -> pd.DataFrame:
    start = pd.Timestamp("2026-06-01T12:00:00Z")
    local_idx = pd.date_range(start, periods=hours * 12 + 1, freq="5min", tz="UTC")
    web_idx = pd.date_range(start, periods=hours * 3 + 1, freq="20min", tz="UTC")
    bas = pd.Series(50.0 + local_offset_f, index=local_idx)
    web = pd.Series(50.0, index=web_idx)
    equip = pd.DataFrame({"outside-air-temp": bas})
    weather = pd.DataFrame({"web-outside-air-temp": web})
    merged = merge_weather(equip, weather)
    return merged


def _fault_hours(frame: pd.DataFrame, params: dict) -> float:
    raw = oat_vs_meteo(frame, params, 300.0)
    confirmed = confirm_fault(raw, poll_seconds=300.0, confirm_seconds=900.0)
    return hours_true(confirmed, 300.0)


def test_seven_degree_offset_confirms_after_asof():
    params = {"oat_err": 5.0, "web_cadence_seconds": 1200.0, "web_asof_margin_seconds": 300.0}
    hours = _fault_hours(_frame(7.0), params)
    assert hours > 0.0
    assert abs(hours - 1.75) < 0.1


def test_three_degree_offset_no_fault():
    params = {"oat_err": 5.0, "web_cadence_seconds": 1200.0, "web_asof_margin_seconds": 300.0}
    hours = _fault_hours(_frame(3.0), params)
    assert hours == 0.0


def test_web_gap_beyond_bound_not_assessed():
    params = {"oat_err": 5.0, "web_cadence_seconds": 1200.0, "web_asof_margin_seconds": 300.0}
    start = pd.Timestamp("2026-06-01T12:00:00Z")
    local_idx = pd.date_range(start, periods=25, freq="5min", tz="UTC")
    web_times = [start, start + pd.Timedelta(minutes=20)]
    web = pd.Series([50.0, 50.0], index=pd.DatetimeIndex(web_times, tz="UTC"))
    bas = pd.Series(57.0, index=local_idx)
    equip = pd.DataFrame({"outside-air-temp": bas})
    weather = pd.DataFrame({"web-outside-air-temp": web})
    merged = merge_weather(equip, weather)
    raw = oat_vs_meteo(merged, params, 300.0)
    # After the web gap exceeds 1500s, samples should not assess as fault.
    tail = raw.iloc[-6:]
    assert not tail.any()


def test_nonzero_cadence_offset_uses_merge_asof_tolerance():
    """20-minute web cadence with 5-minute BAS — as-of tolerance is cadence + margin."""
    params = {"oat_err": 5.0, "web_cadence_seconds": 1200.0, "web_asof_margin_seconds": 300.0}
    start = pd.Timestamp("2026-06-01T12:07:00Z")
    bas_idx = pd.date_range(start, periods=6, freq="5min", tz="UTC")
    web_idx = pd.date_range("2026-06-01T12:00:00Z", periods=3, freq="20min", tz="UTC")
    bas = pd.Series(58.0, index=bas_idx)
    web = pd.Series(50.0, index=web_idx)
    equip = pd.DataFrame({"outside-air-temp": bas})
    weather = pd.DataFrame({"web-outside-air-temp": web})
    merged = merge_weather(equip, weather)
    raw = oat_vs_meteo(merged, params, 300.0)
    assert raw.any()
    assert raw.sum() >= 1


def test_model_primary_bas_series_wins_over_reindexed_web():
    """Authoritative BAS OAT column drives assessment; web is carried as-of only."""
    params = {"oat_err": 5.0, "web_cadence_seconds": 1200.0, "web_asof_margin_seconds": 300.0}
    start = pd.Timestamp("2026-06-01T12:00:00Z")
    bas_idx = pd.date_range(start, periods=8, freq="5min", tz="UTC")
    web_idx = pd.date_range(start, periods=3, freq="20min", tz="UTC")
    bas = pd.Series([50.0, 50.0, 57.0, 57.0, 57.0, 57.0, 50.0, 50.0], index=bas_idx)
    web = pd.Series(50.0, index=web_idx)
    equip = pd.DataFrame({"outside-air-temp": bas})
    weather = pd.DataFrame({"web-outside-air-temp": web})
    native = weather.copy()
    equip.attrs["web_oat_native_frame"] = native
    merged = merge_weather(equip, weather)
    raw = oat_vs_meteo(merged, params, 300.0)
    assert raw.iloc[2:6].all()
    assert not raw.iloc[0:2].any()
