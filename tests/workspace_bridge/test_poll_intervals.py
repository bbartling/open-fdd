"""Standard poll interval helpers."""

from __future__ import annotations

from openfdd_bridge.poll_intervals import POLL_INTERVALS_S, snap_poll_interval


def test_snap_poll_interval_standard_values():
    for s in POLL_INTERVALS_S:
        assert snap_poll_interval(s) == s
    assert snap_poll_interval(0) == 0


def test_snap_poll_interval_legacy():
    assert snap_poll_interval(600) == 900
    assert snap_poll_interval(1200) == 900
