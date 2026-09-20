"""Unit tests for open_fdd/analytics/mv_change_point.py (Wave S4 thin twin).

Loads the module by file path so tests do not require numpy / full analytics package.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MV_MOD = ROOT / "open_fdd" / "analytics" / "mv_change_point.py"


def _load_mv():
    spec = importlib.util.spec_from_file_location("openfdd_mv_change_point_twin", MV_MOD)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class MvChangePointTwinTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mv = _load_mv()

    def test_ols_recovers_known_line(self):
        slope, intercept, r2 = self.mv.ols_fit(
            [1.0, 2.0, 3.0, 4.0], [3.0, 5.0, 7.0, 9.0]
        )
        self.assertAlmostEqual(slope, 2.0, places=9)
        self.assertAlmostEqual(intercept, 1.0, places=9)
        self.assertAlmostEqual(r2, 1.0, places=9)

    def test_demo_seed_savings_near_300(self):
        series = self.mv.demo_seed_series()
        env = self.mv.handle_series(series)
        self.assertEqual(env["query_version"], self.mv.QV_MV_CHANGE_POINT)
        sav = env["coverage"]["savings_reporting_total"]
        self.assertAlmostEqual(sav, 300.0, delta=1.0)
        fit = env["coverage"]["fit"]
        self.assertAlmostEqual(fit["slope"], 2.0, delta=1e-3)
        self.assertAlmostEqual(fit["intercept"], 500.0, delta=1e-2)

    def test_change_point_monthly_direct(self):
        series = self.mv.demo_seed_series()
        rows = series["rows"]
        periods = [r["period"] for r in rows]
        base = {p for p in periods if p <= "2023-12"}
        rep = {p for p in periods if p > "2023-12"}
        fit, out, _ = self.mv.change_point_monthly(
            rows, baseline=base, reporting=rep, dd_kind="hdd"
        )
        self.assertIsNotNone(fit)
        sav = sum(r["savings"] for r in out if r["period_kind"] == "reporting")
        self.assertAlmostEqual(sav, 300.0, delta=1.0)


if __name__ == "__main__":
    unittest.main()
