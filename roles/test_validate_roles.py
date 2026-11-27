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

    def test_new_roles_keep_legacy_keys_and_units(self):
        boiler = role(DOC, "boiler_operating_status")
        self.assertEqual(boiler["legacy_keys"], ["boiler_status"])
        self.assertEqual(boiler["value_type"], "boolean")
        self.assertEqual(boiler["haystack"]["kind"], "Bool")
        self.assertEqual(boiler["haystack"]["markers"], ["boiler", "run", "sensor"])
        filt = role(DOC, "filter_air_pressure_delta")
        self.assertEqual(filt["legacy_keys"], ["filter_dp"])
        self.assertIn("filter_differential_pressure", filt["aliases"])
        self.assertEqual(filt["unit"], "unit:PA")
        self.assertEqual(filt["haystack"]["unit"], "Pa")
        fan = role(DOC, "supply_fan_electric_power")
        self.assertEqual(fan["legacy_keys"], ["fan_power"])
        self.assertEqual(fan["unit"], "unit:KiloW")
        self.assertEqual(fan["haystack"]["unit"], "kW")
        self.assertEqual(fan["s223"]["quantity_kind"], "quantitykind:ElectricPower")

    def test_terminal_discharge_temperature_binds_one_role(self):
        generic = role(DOC, "discharge_air_temperature")
        terminal = role(DOC, "terminal_unit_discharge_air_temperature")
        self.assertIn("airTerminalUnit", generic["haystack"]["equip_forbid"])
        self.assertIn("airTerminalUnit", terminal["haystack"]["equip_markers"])
        self.assertNotIn("s223:TerminalUnit", generic["s223"]["applies_to"])
        self.assertIn("s223:FanCoilUnit", generic["s223"]["applies_to"])
        self.assertFalse(v.parent_constraints_overlap(generic["haystack"], terminal["haystack"]))

    def test_boiler_run_sensor_does_not_bind_the_supply_fan(self):
        """Class run-sensor plus boiler,run,sensor on a boiler parent is only the boiler role."""
        fan = role(DOC, "supply_fan_operating_status")["haystack"]
        boiler = role(DOC, "boiler_operating_status")["haystack"]

        def binds(hs, nf_class, markers, parent):
            if parent & set(hs.get("equip_forbid") or []):
                return False
            if hs.get("equip_markers") and not set(hs["equip_markers"]) <= parent:
                return False
            if set(hs.get("forbid") or []) & markers:
                return False
            if nf_class in hs["classes"]:
                return True
            return set(hs["markers"]) <= markers

        point = ("run-sensor", {"boiler", "run", "sensor"}, {"boiler"})
        self.assertTrue(binds(boiler, *point))
        self.assertFalse(binds(fan, *point))
        ahu = ("run-sensor", {"fan", "run", "sensor"}, {"ahu"})
        self.assertTrue(binds(fan, *ahu))
        self.assertFalse(binds(boiler, *ahu))
        self.assertIn("discharge-run-sensor", fan["classes"])

    def test_command_and_occupancy_values_are_boolean(self):
        for name in ("maximum_cooling_operating_mode_command", "purge_operating_mode_command", "occupancy_status"):
            entry = role(DOC, name)
            self.assertEqual(entry["value_type"], "boolean", name)
            self.assertEqual(entry["haystack"]["kind"], "Bool", name)
            self.assertNotIn("site-defined", entry.get("note", ""), name)
        self.assertEqual(role(DOC, "test_operating_mode_command")["value_type"], "enumeration")


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

    def test_unknown_unit_is_reported(self):
        errs = mutated(lambda d: role(d, "discharge_air_temperature").update(unit="unit:DEG_F"))
        self.assertFlags(errs, "unit unit:DEG_F is not in units")

    def test_ingest_target_must_be_a_known_unit(self):
        def f(d):
            d["ingest_conversions"][0]["to"] = "unit:DEG_F"
        self.assertFlags(mutated(f), "target unit:DEG_F is not in units")

    def test_shared_class_when_parent_constraints_overlap(self):
        def f(d):
            role(d, "discharge_air_temperature")["haystack"].pop("equip_forbid")
        self.assertFlags(mutated(f), "parent constraints overlap")

    def test_boolean_kind_must_be_bool(self):
        def f(d):
            role(d, "occupancy_status")["haystack"]["kind"] = "Str"
        self.assertFlags(mutated(f), "does not match value_type boolean")

    def test_invalid_source_uri(self):
        doc = copy.deepcopy(DOC)
        doc["sources"][0]["url"] = "not a URI"
        errs: list[str] = []
        v.check_schema(doc, v.DEFAULT_SCHEMA, errs)
        self.assertTrue(any("url" in e for e in errs), errs)

    def test_pinned_source_urls_pass_the_schema(self):
        errs: list[str] = []
        v.check_schema(DOC, v.DEFAULT_SCHEMA, errs)
        self.assertEqual(errs, [])

    def test_ontology_sources_require_each_name_once(self):
        missing = copy.deepcopy(DOC)
        missing["sources"] = [s for s in missing["sources"] if s["name"] != "qudt-units"]
        errs = v.check_ontologies(missing, Path("/tmp/roles-ontologies-unused"))
        self.assertTrue(any("qudt-units" in e for e in errs), errs)
        duplicate = copy.deepcopy(DOC)
        duplicate["sources"].append(dict(duplicate["sources"][0]))
        errs = v.check_ontologies(duplicate, Path("/tmp/roles-ontologies-unused"))
        self.assertTrue(any("exactly one 's223'" in e for e in errs), errs)

    def test_explicit_nf_catalog_must_exist(self):
        import io
        from contextlib import redirect_stderr, redirect_stdout
        err, out = io.StringIO(), io.StringIO()
        with redirect_stderr(err), redirect_stdout(out):
            code = v.main([str(v.DEFAULT_ROLES), "--nf-classes", "/tmp/no-such-nf-classes.json"])
        self.assertEqual(code, 1)
        self.assertIn("is missing", err.getvalue())

    def test_schema_errors_return_before_semantic_checks(self):
        import io
        import tempfile
        from contextlib import redirect_stderr, redirect_stdout
        bad = copy.deepcopy(DOC)
        bad.pop("lexicon")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "roles.json"
            path.write_text(json.dumps(bad), encoding="utf-8")
            err, out = io.StringIO(), io.StringIO()
            with redirect_stderr(err), redirect_stdout(out):
                code = v.main([str(path), "--schema", str(v.DEFAULT_SCHEMA)])
        self.assertEqual(code, 1)
        text = err.getvalue()
        self.assertIn("schema:", text)
        self.assertNotIn("Traceback", text)
        self.assertIn("schema,", out.getvalue())


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
