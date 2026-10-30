"""Negative tests for registry/tuning SI cutover diff validation (#1284)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "ci"))

from unit_contract_lib import (  # noqa: E402
    METRIC_UNITS,
    declared_kind,
    load_json,
    validate_param_si_change,
)


class UnitContractSiCutoverDiffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.metric = load_json(METRIC_UNITS)

    def test_value_change_without_unit_change_fails(self) -> None:
        master = {"unit": "in_wc", "kind": "air_pressure", "default": 0.5}
        branch = {"unit": "in_wc", "kind": "air_pressure", "default": 0.6}
        with self.assertRaises(AssertionError) as ctx:
            validate_param_si_change(self.metric, "FC1.eps_dsp", master, branch)
        self.assertIn("value changed without a unit change", str(ctx.exception))

    def test_wrong_si_value_after_unit_change_fails(self) -> None:
        master = {"unit": "in_wc", "kind": "air_pressure", "default": 0.5}
        branch = {"unit": "Pa", "kind": "air_pressure", "default": 999.0}
        with self.assertRaises(AssertionError):
            validate_param_si_change(self.metric, "FC1.eps_dsp", master, branch)

    def test_kind_change_without_unit_change_fails(self) -> None:
        master = {"unit": "degF", "kind": "absolute_temperature", "default": 72.0}
        branch = {"unit": "degF", "kind": "temperature_difference", "default": 72.0}
        with self.assertRaises(AssertionError) as ctx:
            validate_param_si_change(self.metric, "VAV-1.zone_t_lo", master, branch)
        self.assertIn("without a unit change", str(ctx.exception))

    def test_valid_zone_cfm_to_l_per_s_conversion_passes(self) -> None:
        master = {"unit": "cfm", "kind": "volumetric_flow", "default": 25.0}
        branch = {"unit": "L_per_s", "kind": "volumetric_flow", "default": 11.798675}
        validate_param_si_change(self.metric, "VAV-3.flow_on_min", master, branch)

    def test_valid_deadband_delta_conversion_passes(self) -> None:
        master = {"unit": "degF", "kind": "temperature_difference", "default": 1.8}
        branch = {"unit": "degC", "kind": "temperature_difference", "default": 1.0}
        validate_param_si_change(self.metric, "FCU-DEADBAND.deadband", master, branch)

    def test_missing_declared_kind_fails(self) -> None:
        with self.assertRaises(ValueError):
            declared_kind("custom_knob", {"unit": "not_a_real_unit"})


if __name__ == "__main__":
    unittest.main()
