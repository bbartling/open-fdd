"""Smoke and unit tests for scripts/stress/oat_meteo_estimate.py."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STRESS = ROOT / "scripts" / "stress"
MODULE_PATH = STRESS / "oat_meteo_estimate.py"


def load_module():
    if str(STRESS) not in sys.path:
        sys.path.insert(0, str(STRESS))
    spec = importlib.util.spec_from_file_location("oat_meteo_estimate", MODULE_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class OatMeteoEstimateTests(unittest.TestCase):
    mod = None

    @classmethod
    def setUpClass(cls):
        cls.mod = load_module()

    def test_help_and_full_parse(self):
        with self.assertRaises(SystemExit) as ctx:
            self.mod.build_parser().parse_args(["--help"])
        self.assertEqual(ctx.exception.code, 0)
        args = self.mod.build_parser().parse_args(
            [
                "--host",
                "127.0.0.1",
                "--building-id",
                "SYNTH_01",
                "--user",
                "agent",
                "--password",
                "secret",
                "--oa-column",
                "WX.oa_t_a",
                "--web-column",
                "web_oa_t",
            ]
        )
        self.assertEqual(args.building_id, "SYNTH_01")
        self.assertEqual(args.oa_column, "WX.oa_t_a")

    def test_nearest_sample_estimator_on_fixture(self):
        oa_body = {
            "timestamps": [
                "2026-06-01T12:00:00Z",
                "2026-06-01T12:05:00Z",
                "2026-06-01T12:10:00Z",
            ],
            "series": {
                "WX.oa_t_a": [57.0, 57.0, 57.0],
            },
        }
        web_body = {
            "timestamps": [
                "2026-06-01T12:00:00Z",
                "2026-06-01T12:20:00Z",
            ],
            "series": {
                "web_oa_t": [50.0, 50.0],
            },
        }
        result = self.mod.estimate_fault_hours_from_readings(
            oa_body,
            web_body,
            oa_column="WX.oa_t_a",
            web_column="web_oa_t",
            poll_seconds=300.0,
            confirm_seconds=900.0,
        )
        self.assertGreater(result["fault_hours"], 0.0)
        self.assertEqual(result["oa_column"], "WX.oa_t_a")


if __name__ == "__main__":
    unittest.main()
