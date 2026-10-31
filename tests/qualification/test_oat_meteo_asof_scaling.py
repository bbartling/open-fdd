"""T1439: OAT-METEO as-of scaling bench smoke + Postgres mask contract."""

from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STRESS = ROOT / "scripts" / "stress"
BENCH = STRESS / "oat_meteo_asof_scaling_bench.py"


def load_bench():
    if str(STRESS) not in sys.path:
        sys.path.insert(0, str(STRESS))
    spec = importlib.util.spec_from_file_location("oat_meteo_asof_scaling_bench", BENCH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class OatMeteoAsOfScalingBenchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bench = load_bench()

    def test_render_and_exponent_math(self):
        sql = self.bench._render_rule(web_asof_bound_seconds=1500.0)
        self.assertIn("web_intervals AS", sql)
        self.assertNotIn("SELECT d.ref_val\n      FROM web_dedup d", sql)
        exp = self.bench._growth_exponent([700, 4700, 35000], [0.01, 0.28, 10.6])
        self.assertGreater(exp, 1.1)


@unittest.skipUnless(
    os.environ.get("OPENFDD_TEST_DATABASE_URL", "").strip()
    or os.environ.get("OPENFDD_DATABASE_URL", "").strip(),
    "OPENFDD_TEST_DATABASE_URL required for disposable Postgres scaling smoke",
)
class OatMeteoAsOfScalingPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bench = load_bench()
        cls.url = (
            os.environ.get("OPENFDD_TEST_DATABASE_URL", "").strip()
            or os.environ.get("OPENFDD_DATABASE_URL", "").strip()
        )

    def test_t1439_quick_bench_runs_under_timeout(self):
        report = self.bench.run_benchmark(
            database_url=self.url,
            sizes=(700, 4700),
            equipment_count=1,
            web_mode="dense",
            web_asof_bound_seconds=1500.0,
            fdd_timeout_secs=900.0,
        )
        self.assertEqual(len(report["cases"]), 2)
        self.assertGreater(report["timeout_margin_seconds_largest_case"], 0.0)


if __name__ == "__main__":
    unittest.main()
