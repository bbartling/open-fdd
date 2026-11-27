"""Tests for roles/validate_roles.py.

    python3 -m unittest roles/test_validate_roles.py -v
    ROLES_ONTOLOGY_DIR=/path/to/pinned/files python3 -m unittest roles/test_validate_roles.py   # adds the deep check
"""
from __future__ import annotations

import copy
import json
import os
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import validate_roles as v  # noqa: E402

DOC = json.loads(v.DEFAULT_ROLES.read_text(encoding="utf-8"))


def role(doc: dict, name: str) -> dict:
    return next(r for r in doc["roles"] if r["role"] == name)


def mutated(fn) -> list[str]:
    doc = copy.deepcopy(DOC)
    fn(doc)
    return v.check(doc)


class RealFile(unittest.TestCase):
    def test_passes(self):
        errs: list[str] = []
        v.check_schema(DOC, v.DEFAULT_SCHEMA, errs)
        nf = None
        if v.DEFAULT_NF_CLASSES.exists():
            raw = json.loads(v.DEFAULT_NF_CLASSES.read_text(encoding="utf-8"))
            items = raw["classes"] if isinstance(raw, dict) else raw
            nf = {c["name"] if isinstance(c, dict) else c for c in items}
        errs += v.check(DOC, nf)
        self.assertEqual(errs, [])

    def test_every_name_is_derived(self):
        for r in DOC["roles"]:
            self.assertEqual(v.derive(r["s223"], DOC), r["role"])

    def test_grounding_counts_match_extension_terms(self):
        ext = [r["role"] for r in DOC["roles"] if r["grounding"] == "extension"]
        self.assertTrue(all(any(t.startswith("ext:") for t in v.basis_terms(role(DOC, n)["s223"])) for n in ext))

    def test_ratios_are_percent(self):
        for r in DOC["roles"]:
            if r["s223"].get("quantity_kind") == "quantitykind:DimensionlessRatio" and not r["s223"].get("constituent"):
                self.assertEqual(r["unit"], "unit:PERCENT", r["role"])

    def test_command_and_feedback_are_distinct(self):
        cmd = role(DOC, "outdoor_air_intake_damper_position_command")
        fb = role(DOC, "outdoor_air_intake_damper_position")
        self.assertEqual(cmd["s223"]["property_class"], "s223:QuantifiableActuatableProperty")
        self.assertEqual(fb["s223"]["property_class"], "s223:QuantifiableObservableProperty")
        self.assertIn("cmd", cmd["haystack"]["markers"])
        self.assertIn("sensor", fb["haystack"]["markers"])

    def test_suffix_rule(self):
        b = {"property_class": "s223:QuantifiableActuatableProperty", "roles": ["s223:Role-Discharge"],
             "medium": "s223:Fluid-Air", "quantity_kind": "quantitykind:Temperature", "applies_to": []}
        self.assertEqual(v.derive(b, DOC), "discharge_air_temperature_command")
        b["aspects"] = ["s223:Aspect-Setpoint"]
        self.assertEqual(v.derive(b, DOC), "discharge_air_temperature_setpoint")
        b = {"property_class": "s223:EnumeratedObservableProperty", "equipment_role": "s223:Role-Supply",
             "equipment": "s223:Fan", "enumeration_kind": "s223:Binary-OnOff",
             "aspects": ["s223:Aspect-OperatingStatus"], "applies_to": []}
        self.assertEqual(v.derive(b, DOC), "supply_fan_operating_status")


class Mutations(unittest.TestCase):
    def assertFlags(self, errs: list[str], text: str):
        self.assertTrue(any(text in e for e in errs), f"{text!r} not in {errs}")

    def test_wrong_name(self):
        errs = mutated(lambda d: role(d, "mixed_air_temperature").update(role="mat"))
        self.assertFlags(errs, "derivation gives 'mixed_air_temperature'")

    def test_unit_does_not_fit_quantity_kind(self):
        errs = mutated(lambda d: role(d, "discharge_air_temperature").update(unit="unit:PA"))
        self.assertFlags(errs, "does not apply to quantitykind:Temperature")

    def test_fraction_ratio(self):
        def f(d):
            d["units"]["unit:UNITLESS"] = {"wire": "UNITLESS", "haystack": None, "quantity_kinds": ["DimensionlessRatio"],
                                           "range": [0, 1]}
            role(d, "cooling_valve_position_command").update(unit="unit:UNITLESS", range=[0, 1])
        self.assertFlags(mutated(f), "ratios use unit:PERCENT")

    def test_setpoint_must_forbid_max(self):
        errs = mutated(lambda d: role(d, "discharge_air_volume_flow_rate_setpoint")["haystack"].update(forbid=["min", "total"]))
        self.assertFlags(errs, "a setpoint must forbid max and min")

    def test_writable_subset_needs_forbid(self):
        def f(d):
            hs = role(d, "discharge_air_volume_flow_rate_setpoint")["haystack"]
            hs["forbid"] = [m for m in hs["forbid"] if m != "max"]
        self.assertFlags(mutated(f), "discharge_air_volume_flow_rate_maximum point also matches it")

    def test_undeclared_custom_marker(self):
        errs = mutated(lambda d: d["haystack"]["custom_markers"].pop("smoke"))
        self.assertFlags(errs, "custom marker 'smoke' is not declared")

    def test_unflagged_extension(self):
        errs = mutated(lambda d: role(d, "mixed_air_temperature").update(grounding="s223"))
        self.assertFlags(errs, "grounding must be extension")

    def test_extension_needs_closest(self):
        errs = mutated(lambda d: d["lexicon"]["ext:Mixed"].pop("closest"))
        self.assertFlags(errs, "an extension needs closest and why")

    def test_observable_never_writable(self):
        errs = mutated(lambda d: role(d, "supply_fan_operating_status").update(writable="model"))
        self.assertFlags(errs, "only an actuatable property may be writable")

    def test_writer_needs_writable(self):
        errs = mutated(lambda d: role(d, "cooling_valve_position_command").update(writable="never"))
        self.assertFlags(errs, "nf-hvac-functional-test writes it")

    def test_wrong_function_marker(self):
        def f(d):
            hs = role(d, "outdoor_air_intake_damper_position_command")["haystack"]
            hs["markers"] = ["outside", "damper", "sensor"]
        self.assertFlags(mutated(f), "needs exactly the function marker 'cmd'")

    def test_redundant_alt_set(self):
        def f(d):
            hs = role(d, "maximum_cooling_operating_mode_command")["haystack"]
            hs["alt_markers"] = [["vav", "max", "cool", "cmd"]]
        self.assertFlags(mutated(f), "is redundant with markers")

    def test_marker_outside_haystack(self):
        errs = mutated(lambda d: role(d, "discharge_air_static_pressure")["haystack"]["markers"].append("ductStatic"))
        self.assertFlags(errs, "marker 'ductStatic' is not in haystack.markers")

    def test_alias_collision(self):
        errs = mutated(lambda d: role(d, "zone_air_temperature")["aliases"].append("outside_air_temperature"))
        self.assertFlags(errs, "alias 'outside_air_temperature'")

    def test_unknown_nf_class(self):
        errs = v.check(copy.deepcopy(DOC), nf_classes={"zone-air-temp-sensor"})
        self.assertFlags(errs, "is not in nf_classes.json")


@unittest.skipUnless(os.environ.get("ROLES_ONTOLOGY_DIR"), "set ROLES_ONTOLOGY_DIR to the pinned ontology files")
class Ontologies(unittest.TestCase):
    def test_terms_exist_in_pinned_files(self):
        self.assertEqual(v.check_ontologies(DOC, Path(os.environ["ROLES_ONTOLOGY_DIR"])), [])

    def test_invented_term_fails(self):
        doc = copy.deepcopy(DOC)
        doc["lexicon"]["s223:Role-Mixed"] = {"token": "mixed_role"}
        errs = v.check_ontologies(doc, Path(os.environ["ROLES_ONTOLOGY_DIR"]))
        self.assertTrue(any("s223:Role-Mixed is not defined" in e for e in errs), errs)


if __name__ == "__main__":
    unittest.main()
