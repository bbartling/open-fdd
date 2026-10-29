"""W4f analytics SI parity — pandas thresholds match SQL bodies (#1284)."""

from __future__ import annotations

import os
import unittest
from pathlib import Path

import pandas as pd

from open_fdd.analytics.core import _mech_oat_sql_bin, mech_cooling_oat_bins
from open_fdd.analytics.si_thresholds import (
    ECON_DIAG_DT_MIN_C,
    MECH_OAT_BIN_LABELS,
    SENSOR_TEMP_RANGE_MAX_C,
    SENSOR_TEMP_RANGE_MIN_C,
)

REPO = Path(__file__).resolve().parents[2]


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


class W4fAnalyticsP2Tests(unittest.TestCase):
    def test_nineteen_analytics_sql_bodies_shipped(self) -> None:
        from scripts.stress.si_cutover import ci_analytics_p2 as cap2

        stems = cap2.all_analytics_sql_stems()
        self.assertEqual(len(stems), 19)
        paths = {f"sql/analytics/postgres/queries/{s}.sql" for s in stems}
        missing = paths - cap2.registry_sql_paths()
        self.assertFalse(
            missing,
            f"registry missing shipped analytics SQL: {sorted(missing)}",
        )

    @unittest.skipUnless(
        os.environ.get("OPENFDD_DATABASE_URL", "").strip(),
        "OPENFDD_DATABASE_URL required for analytics P2 Timescale parity",
    )
    def test_analytics_p2_all_queries_on_si_ci_seeds(self) -> None:
        from scripts.ci import unit_contract_lib as uc
        from scripts.stress.si_cutover import ci_analytics_p2 as cap2
        from scripts.stress.si_cutover import ci_timescale_sql as cts
        from scripts.stress.si_cutover.parity_chain import load_all_ip_goldens

        parity = cts._load_parity_module()
        conn = parity.connect_with_retry(os.environ["OPENFDD_DATABASE_URL"])
        try:
            goldens = load_all_ip_goldens()
            metric = uc.load_json(uc.METRIC_UNITS)
            results = cap2.run_p2_all_analytics(conn, goldens, metric)
            _total, errors = cap2.summarize(results)
        finally:
            conn.close()
        self.assertEqual(errors, [], "\n".join(errors[:20]))


if __name__ == "__main__":
    unittest.main()
