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
from scripts.stress.si_cutover.ci_fixtures_lib import column_quantity_unit

REPO = Path(__file__).resolve().parents[2]


class W4fAnalyticsSiTests(unittest.TestCase):
    def test_frozen_ip_fixture_source_units_do_not_follow_product_display_defaults(self) -> None:
        # Historical fixture values stay IP even when current product defaults are SI.
        self.assertEqual(column_quantity_unit("zone-air-temp"), ("absolute_temperature", "degF"))
        self.assertAlmostEqual((72.0 - 32.0) * 5.0 / 9.0, 22.2222222222, places=8)
        self.assertEqual(column_quantity_unit("duct-static-pressure"), ("air_pressure", "inWC"))
        self.assertAlmostEqual(1.0 * 249.08891, 249.08891, places=4)
        self.assertEqual(column_quantity_unit("zone-airflow"), ("volumetric_flow", "cfm"))
        self.assertAlmostEqual(100.0 * 0.47194745, 47.1947, places=3)

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
            display_units="imperial",
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
            display_units="metric",
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
    def test_ip_goldens_no_pending_w4_cells(self) -> None:
        import json

        from scripts.stress.si_cutover.ci_timescale_sql import PENDING_W4, SI_SQL_PACK_AVAILABLE

        if not SI_SQL_PACK_AVAILABLE:
            self.skipTest("SI SQL pack not marked available")
        goldens_dir = REPO / "tests" / "fixtures" / "si_cutover" / "ip_goldens"
        stale: list[str] = []
        for path in sorted(goldens_dir.glob("*.json")):
            doc = json.loads(path.read_text(encoding="utf-8"))
            for row in doc.get("p2_si_pairs") or []:
                if str(row.get("sql_si_status") or "") == PENDING_W4:
                    stale.append(f"{path.name}:{row.get('rule_id')}/{row.get('utc_day')}")
        self.assertFalse(stale, f"pending_W4 cells remain: {stale[:10]}")

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

    def test_analytics_p1_p2_offline_all_queries(self) -> None:
        from scripts.stress.si_cutover import analytics_parity as ap

        p1, p2 = ap.run_analytics_stages(scope=None)
        self.assertEqual(list(p1.errors), [], "\n".join(p1.errors[:20]))
        self.assertEqual(list(p2.errors), [], "\n".join(p2.errors[:20]))
        for cov in p2.structured:
            self.assertGreater(cov["p1_rows"], 0, cov)
            self.assertGreater(cov["p2_rows"], 0, cov)
        self.assertEqual(len(p2.structured), 19)

    def test_analytics_mutation_fails_p1(self) -> None:
        from scripts.stress.si_cutover import analytics_parity as ap

        p1, _p2 = ap.run_analytics_stages(
            scope={"mechanical_cooling_oat_bins"},
            param_hook=ap.t1284_4_analytics_double_conversion,
        )
        self.assertTrue(p1.errors)

    @unittest.skipUnless(
        os.environ.get("OPENFDD_DATABASE_URL", "").strip(),
        "OPENFDD_DATABASE_URL required for analytics SQL SI golden check",
    )
    def test_analytics_sql_si_goldens_match_live_sql(self) -> None:
        from scripts.stress.si_cutover import analytics_parity as ap
        from scripts.stress.si_cutover import ci_timescale_sql as cts

        parity = cts._load_parity_module()
        conn = parity.connect_with_retry(os.environ["OPENFDD_DATABASE_URL"])
        try:
            n, errors = ap.check_goldens_against_db(conn)
        finally:
            conn.close()
        self.assertEqual(errors, [], "\n".join(errors[:20]))
        self.assertGreater(n, 0)

if __name__ == "__main__":
    unittest.main()
