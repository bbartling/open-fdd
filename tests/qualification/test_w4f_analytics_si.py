"""W4f analytics SI parity — pandas thresholds match SQL bodies (#1284)."""

from __future__ import annotations

import unittest

import pandas as pd

from open_fdd.analytics.core import _mech_oat_sql_bin, mech_cooling_oat_bins
from open_fdd.analytics.si_thresholds import (
    ECON_DIAG_DT_MIN_C,
    MECH_OAT_BIN_LABELS,
    SENSOR_TEMP_RANGE_MAX_C,
    SENSOR_TEMP_RANGE_MIN_C,
)


class W4fAnalyticsSiTests(unittest.TestCase):
    def test_economizer_dt_min_is_guideline_36_si(self) -> None:
        self.assertAlmostEqual(ECON_DIAG_DT_MIN_C, 10.0 * 5.0 / 9.0, places=9)

    def test_mech_oat_bin_labels_match_sql(self) -> None:
        samples = [
            (9.9, "<10"),
            (10.0, "10-16"),
            (18.333333333333332, "16-21"),
            (20.0, "16-21"),
            (22.0, "21-27"),
            (30.0, "27-32"),
            (40.0, ">=32"),
        ]
        for oat_c, label in samples:
            _, got = _mech_oat_sql_bin(oat_c)
            self.assertEqual(got, label, f"oat_c={oat_c}")
        self.assertEqual(len(MECH_OAT_BIN_LABELS), 6)

    def test_sensor_range_limits_si(self) -> None:
        self.assertEqual(SENSOR_TEMP_RANGE_MIN_C, -40.0)
        self.assertAlmostEqual(SENSOR_TEMP_RANGE_MAX_C, 121.11111111111111, places=9)

    def test_pandas_ip_and_si_mech_hours_match_physical(self) -> None:
        idx = pd.date_range("2026-01-01", periods=12, freq="5min", tz="UTC")
        role_map = {
            "CHILLER_1": {
                "equipType": "chiller",
                "chiller-status": "chiller-status",
                "outside-air-temp": "outside-air-temp",
            }
        }
        imp = mech_cooling_oat_bins(
            {
                "CHILLER_1": pd.DataFrame(
                    {
                        "timestamp_utc": idx,
                        "chiller-status": 1.0,
                        "outside-air-temp": 72.0,
                    },
                    index=idx,
                )
            },
            role_map,
            unit_system="imperial",
            prefer_web_oat=False,
        )
        met = mech_cooling_oat_bins(
            {
                "CHILLER_1": pd.DataFrame(
                    {
                        "timestamp_utc": idx,
                        "chiller-status": 1.0,
                        "outside-air-temp": (72.0 - 32.0) * 5.0 / 9.0,
                    },
                    index=idx,
                )
            },
            role_map,
            unit_system="metric",
            prefer_web_oat=False,
        )
        self.assertFalse(imp.empty)
        self.assertFalse(met.empty)
        self.assertAlmostEqual(
            float(imp["runtime_hours"].sum()),
            float(met["runtime_hours"].sum()),
            places=6,
        )


if __name__ == "__main__":
    unittest.main()
