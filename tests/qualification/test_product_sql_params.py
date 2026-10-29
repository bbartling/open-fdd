"""Product SQL parameter path for SI parity P0 (#1284 W3)."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
STRESS = REPO / "scripts" / "stress" / "si_cutover"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class ProductSqlParamsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.psp = _load("product_sql_params_testmod", STRESS / "product_sql_params.py")
        cls.cfl = _load(
            "ci_fixtures_lib_testmod",
            STRESS / "ci_fixtures_lib.py",
        )

    def test_fc1_effective_mode_delay_uses_registry_defaults(self) -> None:
        rules = {str(r["rule_id"]): r for r in self.cfl.load_rule_registry()}
        fc1 = rules["FC1"]
        params = self.cfl.rule_params_from_registry(fc1)
        self.assertEqual(float(params.get("mode_delay_min", 0)), 10.0)
        self.assertEqual(self.psp.product_effective_mode_delay_min(params), 10.0)
        self.assertIsNone(self.psp.p0_value_mismatch_reason("FC1", params))

    def test_render_rule_applies_runtime_mode_delay_holdoff(self) -> None:
        rules = {str(r["rule_id"]): r for r in self.cfl.load_rule_registry()}
        fc1 = rules["FC1"]
        params = self.cfl.rule_params_from_registry(fc1)
        poll = 300.0
        sql = self.psp.render_rule_sql_product("FC1", poll, registry_params=params)
        effective = self.psp.product_effective_mode_delay_min(params)
        self.assertEqual(effective, 10.0)
        # MODE_DELAY_ROWS=2 → ROWS BETWEEN 1 PRECEDING (see render_rule.py)
        self.assertIn("ROWS BETWEEN 1 PRECEDING AND CURRENT ROW", sql)

    def test_gl36_mode_delay_uses_max_of_mode_and_startup(self) -> None:
        import pandas as pd
        from open_fdd.rules import cookbook_catalog as cb

        idx = pd.date_range("2026-01-01", periods=6, freq="5min", tz="UTC")
        d = pd.DataFrame(
            {
                "heating-valve": [0.0, 0.0, 0.0, 0.5, 0.5, 0.5],
                "cooling-valve": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                "outside-air-damper": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                "fan-cmd": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
            },
            index=idx,
        )
        # max(10, 5) min → 2 samples at 5 min poll; unstable right after mode change at index 3
        stable = cb._gl36_mode_stable(d, {"mode_delay_min": 10.0, "startup_delay_min": 5.0}, 300.0)
        self.assertFalse(bool(stable.iloc[3]))
        self.assertTrue(bool(stable.iloc[0]))


if __name__ == "__main__":
    unittest.main()
