"""FC GL36 sensor tolerance params use registry kind temperature_difference (#1450)."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

from scripts.ci.unit_contract_lib import (
    METRIC_UNITS,
    convert_to_canonical,
    infer_kind,
    load_json,
)

REPO = Path(__file__).resolve().parents[2]
REGISTRY = REPO / "sql" / "fdd" / "registry.yaml"
TUNING = REPO / "sql" / "fdd" / "tuning_catalog.json"

FC_RULES = frozenset(tuple(f"FC{i}" for i in range(1, 16)) + ("FC13-SAT-HIGH",))
_NOT_TEMP_EPS = frozenset({"eps_dsp", "eps_vfd_spd"})


def _is_gl36_temp_tolerance(name: str, unit: str) -> bool:
    if name == "delta_supply_fan":
        return True
    if not name.startswith("eps_") or name in _NOT_TEMP_EPS:
        return False
    return unit in ("degF", "degC", "°F", "degF_delta", "degC_delta")


def _fc_tolerance_params(registry_doc: dict) -> list[tuple[str, str, dict]]:
    out: list[tuple[str, str, dict]] = []
    for rule in registry_doc.get("rules") or []:
        rid = str(rule.get("rule_id") or "")
        if rid not in FC_RULES:
            continue
        for name, spec in (rule.get("parameters") or {}).items():
            if not isinstance(spec, dict):
                continue
            unit = str(spec.get("unit") or "")
            if not _is_gl36_temp_tolerance(str(name), unit):
                continue
            out.append((rid, str(name), spec))
    return out


class FcToleranceParamKindTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.metric = load_json(METRIC_UNITS)
        cls.registry = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
        cls.tuning = load_json(TUNING)
        cls.tuning_by_rule = {
            str(r["rule_id"]): r for r in cls.tuning.get("rules") or [] if r.get("rule_id")
        }

    def test_registry_tolerance_kind_is_temperature_difference(self) -> None:
        bad: list[str] = []
        for rid, name, spec in _fc_tolerance_params(self.registry):
            kind = str(spec.get("kind") or "")
            unit = str(spec.get("unit") or "")
            if kind != "temperature_difference":
                bad.append(f"{rid}.{name} kind={kind!r}")
            if infer_kind(name, unit) != "temperature_difference":
                bad.append(f"{rid}.{name} infer_kind mismatch unit={unit!r}")
        self.assertEqual(bad, [], "FC tolerance params must declare temperature_difference")

    def test_tuning_catalog_tolerance_kind_matches_registry(self) -> None:
        bad: list[str] = []
        for rid, name, spec in _fc_tolerance_params(self.registry):
            rule = self.tuning_by_rule.get(rid) or {}
            tparam = (rule.get("parameters") or {}).get(name)
            if not isinstance(tparam, dict):
                bad.append(f"{rid}.{name} missing in tuning_catalog")
                continue
            if str(tparam.get("kind")) != "temperature_difference":
                bad.append(f"{rid}.{name} tuning kind={tparam.get('kind')!r}")
        self.assertEqual(bad, [])

    def test_tolerance_conversion_is_scale_only_no_fahrenheit_offset(self) -> None:
        """1.15 °F Δ must map to 0.638… °C Δ, not absolute-offset conversion."""
        degf_delta = 1.15
        as_delta = convert_to_canonical(
            self.metric, "temperature_difference", degf_delta, "degF_delta"
        )
        as_absolute = convert_to_canonical(
            self.metric, "absolute_temperature", degf_delta, "degF"
        )
        self.assertAlmostEqual(as_delta, degf_delta * 5.0 / 9.0, places=6)
        self.assertNotAlmostEqual(as_delta, as_absolute, places=3)
        for rid, name, spec in _fc_tolerance_params(self.registry):
            if str(spec.get("unit")) != "degC":
                continue
            default = float(spec.get("default", 0))
            back = convert_to_canonical(
                self.metric,
                "temperature_difference",
                default,
                "degC_delta",
            )
            self.assertAlmostEqual(
                default,
                back,
                places=6,
                msg=f"{rid}.{name} degC_delta canonical round-trip",
            )


if __name__ == "__main__":
    unittest.main()
