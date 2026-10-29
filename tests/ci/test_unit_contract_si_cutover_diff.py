"""Negative tests for registry/tuning SI cutover diff validation (#1284)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "ci"))

from unit_contract_lib import (  # noqa: E402
    METRIC_UNITS,
    _validate_registry_param_si_change,
    load_json,
)


class UnitContractSiCutoverDiffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.metric = load_json(METRIC_UNITS)

    def test_value_change_without_unit_or_kind_fails(self) -> None:
        master = {"unit": "inWC", "kind": "pressure", "default": 0.5}
        branch = {"unit": "inWC", "kind": "pressure", "default": 0.6}
        with self.assertRaises(AssertionError) as ctx:
            _validate_registry_param_si_change(
                self.metric,
                rule_id="FC1",
                branch_key="eps_dsp",
                master=master,
                branch=branch,
            )
        self.assertIn("without unit/kind change", str(ctx.exception))

    def test_wrong_si_value_after_unit_change_fails(self) -> None:
        master = {"unit": "inWC", "kind": "air_pressure", "default": 0.5}
        branch = {"unit": "Pa", "kind": "air_pressure", "default": 999.0}
        with self.assertRaises(AssertionError) as ctx:
            _validate_registry_param_si_change(
                self.metric,
                rule_id="FC1",
                branch_key="eps_dsp",
                master=master,
                branch=branch,
            )
        self.assertIn("SI value", str(ctx.exception))

    def test_kind_change_without_unit_change_fails(self) -> None:
        master = {"unit": "°F", "kind": "temperature", "default": 72.0}
        branch = {"unit": "°F", "kind": "temperature_difference", "default": 72.0}
        with self.assertRaises(AssertionError) as ctx:
            _validate_registry_param_si_change(
                self.metric,
                rule_id="VAV-1",
                branch_key="comfort_lo",
                master=master,
                branch=branch,
            )
        self.assertIn("kind changed without unit change", str(ctx.exception))

    def test_valid_inwc_to_pa_conversion_passes(self) -> None:
        master = {"unit": "inWC", "kind": "air_pressure", "default": 0.5}
        branch = {"unit": "Pa", "kind": "air_pressure", "default": 124.42}
        _validate_registry_param_si_change(
            self.metric,
            rule_id="FC1",
            branch_key="eps_dsp",
            master=master,
            branch=branch,
        )


if __name__ == "__main__":
    unittest.main()
