"""Counterexamples for W4f analytics thresholds awaiting physical-policy review."""

from __future__ import annotations

import unittest

import pandas as pd

from scripts.stress.si_cutover.ci_analytics_oracles import (
    _melt_si_frame,
    oracle_mv_change_point_daily,
    oracle_pid_hunting_proxy,
)


def _long_zone(values: list[float], timestamps: pd.DatetimeIndex) -> pd.DataFrame:
    frame = pd.DataFrame({"zone_t": values}, index=timestamps)
    long = _melt_si_frame(frame, "equip:counterexample")
    long["role"] = "zone_t"
    long["openfdd_key"] = "equip:counterexample.zone_t"
    return long


class W4fThresholdInvarianceCounterexamples(unittest.TestCase):
    @unittest.expectedFailure
    def test_pid_hunting_proxy_is_invariant_for_same_physical_spread(self) -> None:
        """A 9°F sample deviation equals 5°C, but the current literal-8 gates differ."""
        timestamps = pd.date_range("2026-01-01T00:00:00Z", periods=24, freq="h")
        values_f = [63.0, 81.0] * 12
        values_c = [(v - 32.0) * 5.0 / 9.0 for v in values_f]
        ip = oracle_pid_hunting_proxy(_long_zone(values_f, timestamps)).rows[0][6]
        si = oracle_pid_hunting_proxy(_long_zone(values_c, timestamps)).rows[0][6]
        self.assertEqual(ip, si)

    @unittest.expectedFailure
    def test_change_point_is_invariant_for_same_physical_daily_means(self) -> None:
        """32→38°F is 0→3.33°C; current absolute 1.0 floor selects different keys."""
        timestamps = list(pd.date_range("2026-01-01T00:00:00Z", periods=6, freq="4h"))
        timestamps += list(pd.date_range("2026-01-02T00:00:00Z", periods=6, freq="4h"))
        values_f = [32.0] * 6 + [38.0] * 6
        values_c = [(v - 32.0) * 5.0 / 9.0 for v in values_f]
        ip = oracle_mv_change_point_daily(_long_zone(values_f, pd.DatetimeIndex(timestamps))).rows
        si = oracle_mv_change_point_daily(_long_zone(values_c, pd.DatetimeIndex(timestamps))).rows
        self.assertEqual(len(ip), len(si))


if __name__ == "__main__":
    unittest.main()
