"""#1459: pandas mode-delay holdoff shares one definition with product SQL."""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

import pandas as pd

from open_fdd.rules import cookbook_catalog as cb
from open_fdd.rules.mode_delay import (
    PRODUCT_MODE_DELAY_MIN_DEFAULT,
    effective_mode_delay_min,
    fan_restart_stable,
    mode_delay_rows,
)

REPO = Path(__file__).resolve().parents[2]


class ModeDelaySharedTest(unittest.TestCase):
    def test_default_matches_runtime_defaults_json(self) -> None:
        doc = json.loads((REPO / "sql" / "fdd" / "runtime_defaults.json").read_text())
        self.assertEqual(float(doc["MODE_DELAY_MIN"]), PRODUCT_MODE_DELAY_MIN_DEFAULT)

    def test_default_matches_params_rs(self) -> None:
        src = (REPO / "crates" / "fdd_rules" / "src" / "params.rs").read_text()
        m = re.search(r'\("MODE_DELAY_MIN",\s*"([0-9.]+)"\)', src)
        self.assertIsNotNone(m)
        self.assertEqual(float(m.group(1)), PRODUCT_MODE_DELAY_MIN_DEFAULT)

    def test_cookbook_param_default_is_product_default(self) -> None:
        fc1 = next(r for r in cb.RULES if r.id == "FC1")
        self.assertEqual(fc1.defaults()["mode_delay_min"], PRODUCT_MODE_DELAY_MIN_DEFAULT)

    def test_effective_is_max_of_mode_and_startup(self) -> None:
        self.assertEqual(effective_mode_delay_min({"mode_delay_min": 10, "startup_delay_min": 0}), 10.0)
        self.assertEqual(effective_mode_delay_min({"mode_delay_min": 10, "startup_delay_min": 15}), 15.0)

    def test_missing_param_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "startup_delay_min"):
            effective_mode_delay_min({"mode_delay_min": 10})
        with self.assertRaisesRegex(ValueError, "mode_delay_min"):
            effective_mode_delay_min({"startup_delay_min": 0})

    def test_rows_match_render_rule(self) -> None:
        # render_rule.py: max(1, ceil(min*60/poll)); 10 min @ 300 s -> 2 rows (1 PRECEDING)
        self.assertEqual(mode_delay_rows(10.0, 300.0), 2)
        self.assertEqual(mode_delay_rows(0.0, 300.0), 1)
        self.assertEqual(mode_delay_rows(11.0, 300.0), 3)

    def test_fan_restart_suppresses_first_rows_minus_one(self) -> None:
        fan = pd.Series([False, False, True, True, True])
        self.assertEqual(fan_restart_stable(fan, 2).tolist(), [False, False, False, True, True])

    def test_fc1_missing_eps_dsp_raises(self) -> None:
        idx = pd.date_range("2026-01-05", periods=3, freq="5min", tz="UTC")
        d = pd.DataFrame(
            {"duct-static-pressure": 1.0, "duct-static-pressure-sp": 2.0, "fan-status": 1}, index=idx
        )
        with self.assertRaises(KeyError):
            cb.fc1(d, {"eps_vfd_spd": 0.13, "mode_delay_min": 10, "startup_delay_min": 0}, 300.0)


if __name__ == "__main__":
    unittest.main()
