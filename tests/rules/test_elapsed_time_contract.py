"""Elapsed-time contract for the pandas oracle.

Immediate confirmation of the same one-hour fault agrees across a regular
1, 5, and 15 minute grid within one second. The last sample adds no interval.
A fixed confirmation delay may differ by one sample of the coarsest grid
(15 minutes). A gap longer than one hour is unknown: fault hours stay inside
the eligible covered duration and below the first-to-last span.
"""

from __future__ import annotations

import pandas as pd

from open_fdd.rules.base import confirm_fault, hours_true

SECOND_HOURS = 1.0 / 3600.0
CADENCE_TOLERANCE_HOURS = 15.0 / 60.0
START = "2026-06-01T00:00:00Z"


def _fault(step: str, *, minutes: int = 60, confirm_seconds: float = 0.0) -> float:
    index = pd.date_range(START, end=pd.Timestamp(START) + pd.Timedelta(minutes=minutes), freq=step, tz="UTC")
    raw = pd.Series(True, index=index)
    confirmed = confirm_fault(raw, poll_seconds=300.0, confirm_seconds=confirm_seconds)
    return float(hours_true(confirmed, 300.0))


def test_regular_cadence_agrees_when_confirmation_is_immediate():
    hours = [_fault("1min"), _fault("5min"), _fault("15min")]
    for value in hours:
        assert abs(value - 1.0) <= SECOND_HOURS
    assert max(hours) - min(hours) <= CADENCE_TOLERANCE_HOURS


def test_gap_longer_than_one_hour_is_unknown():
    first = pd.date_range(START, periods=31, freq="1min", tz="UTC")
    second = pd.date_range("2026-06-01T03:30:00Z", periods=31, freq="1min", tz="UTC")
    index = first.append(second)
    raw = pd.Series(True, index=index)
    confirmed = confirm_fault(raw, poll_seconds=300.0, confirm_seconds=0.0)
    fault = float(hours_true(confirmed, 300.0))
    span = (index.max() - index.min()).total_seconds() / 3600.0
    assert abs(fault - 1.0) <= SECOND_HOURS
    assert abs(span - 4.0) <= SECOND_HOURS
    assert fault + 1.0 < span


def test_ten_minute_confirm_needs_ten_eligible_minutes():
    assert _fault("1min", minutes=9, confirm_seconds=600.0) == 0.0
    assert abs(_fault("1min", minutes=10, confirm_seconds=600.0) - (60.0 / 3600.0)) <= SECOND_HOURS
    fine = _fault("1min", confirm_seconds=600.0)
    coarse = _fault("15min", confirm_seconds=600.0)
    assert abs(fine - (51.0 / 60.0)) <= SECOND_HOURS
    assert abs(coarse - 1.0) <= SECOND_HOURS
    assert abs(fine - coarse) <= CADENCE_TOLERANCE_HOURS
