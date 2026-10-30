"""W4a FC1–FC15 + FC13-SAT-HIGH registry parameters are SI with correct kinds (#1450)."""

from __future__ import annotations

import math
import unittest
from pathlib import Path

import yaml

from scripts.ci.unit_contract_lib import load_json

REPO = Path(__file__).resolve().parents[2]
REGISTRY = REPO / "sql" / "fdd" / "registry.yaml"
TUNING = REPO / "sql" / "fdd" / "tuning_catalog.json"

FC_RULES = frozenset(tuple(f"FC{i}" for i in range(1, 16)) + ("FC13-SAT-HIGH",))
IMPERIAL_UNITS = frozenset({"degF", "°F", "degF_delta", "inwc", "in_wc", "cfm"})
# Every FC temperature parameter is a tolerance/threshold difference, never an absolute.
TEMPERATURE_UNITS = frozenset({"degC", "°C", "degC_delta"})


def _fc_params(rules: list[dict]) -> dict[tuple[str, str], dict]:
    out: dict[tuple[str, str], dict] = {}
    for rule in rules:
        rid = str(rule.get("rule_id") or "")
        if rid not in FC_RULES:
            continue
        for name, spec in (rule.get("parameters") or {}).items():
            if isinstance(spec, dict):
                out[(rid, str(name))] = spec
    return out


class FcSiParamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = _fc_params(yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))["rules"])
        cls.tuning = _fc_params(load_json(TUNING)["rules"])

    def test_no_imperial_units(self) -> None:
        bad = [f"{k}: {s.get('unit')}" for k, s in self.registry.items() if s.get("unit") in IMPERIAL_UNITS]
        self.assertEqual(bad, [])

    def test_temperatures_are_differences(self) -> None:
        bad = [
            f"{k}: {s.get('kind')}"
            for k, s in self.registry.items()
            if s.get("unit") in TEMPERATURE_UNITS and s.get("kind") != "temperature_difference"
        ]
        self.assertEqual(bad, [])

    def test_mix_tol_is_delta_converted(self) -> None:
        for (rid, name), spec in self.registry.items():
            if name in ("mix_tol", "supply_tol"):
                self.assertTrue(math.isclose(float(spec["default"]), 1.15 * 5.0 / 9.0, abs_tol=1e-9), (rid, name))
                self.assertGreaterEqual(float(spec["min"]), 0.0, (rid, name))
                self.assertGreater(float(spec["step"]), 0.0, (rid, name))

    def test_tuning_matches_registry(self) -> None:
        shared = set(self.registry) & set(self.tuning)
        self.assertTrue(shared)
        for key in sorted(shared):
            spec = self.registry[key]
            tun = self.tuning[key]
            for field in ("unit", "kind"):
                self.assertEqual(spec.get(field), tun.get(field), (key, field))
            for field in ("default", "min", "max", "step"):
                if field in spec:
                    self.assertTrue(math.isclose(float(spec[field]), float(tun[field]), abs_tol=1e-9), (key, field))


if __name__ == "__main__":
    unittest.main()
