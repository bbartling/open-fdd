"""Independent RDF/SPARQL qualification and deliberately broken controls."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/qualification/semantic/qualify.py"
SPEC = importlib.util.spec_from_file_location("semantic_qualify", SCRIPT)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mod)
CANDIDATE = "928a98ef7735320ae5127f9dafd4c1fdefe0c7f9"


class SemanticQualificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # Required suite: a missing parser is a test failure, never a skip/PASS.
        mod.rdf()
        cls.model = (mod.FIXTURES / "valid.ttl").read_bytes()
        cls.expected = mod.load_json(mod.FIXTURES / "expected.json")

    def test_known_answer_model_uses_real_sparql_and_exact_scopes(self) -> None:
        result = mod.qualify(self.model, self.expected, CANDIDATE)
        self.assertEqual(result["status"], "PASS", result)
        self.assertGreater(result["assertions_count"], 50)
        self.assertGreater(result["comparison_count"], 20)
        self.assertEqual(len(result["query_sha256"]), 6)
        self.assertEqual(result["observed_point_count"], 10)
        selections = {item["id"]: item for item in result["selections"]}
        self.assertEqual(selections["SAT-SP"]["point_ids"], ["urn:qa:point/setpoint"])
        self.assertEqual(selections["SAT-AMBIGUOUS"]["readiness"], "AMBIGUOUS")
        self.assertEqual(selections["SAT-APPROVED"]["selected_point"], "urn:qa:point/measured")
        self.assertNotIn("urn:qa:point/near_prefix", selections["SAT-APPROVED"]["point_ids"])
        self.assertNotIn("urn:qa:point/foreign", selections["SAT-APPROVED"]["point_ids"])
        self.assertFalse(result["candidate_product_qualified"])

    def test_all_deliberately_broken_controls_are_rejected(self) -> None:
        report = mod.suite(CANDIDATE)
        self.assertEqual(report["status"], "PASS", report)
        self.assertEqual(report["control_count"], 13)
        for case in report["cases"]:
            with self.subTest(case=case["id"]):
                self.assertEqual(case["control_status"], "PASS", case)
                self.assertEqual(case["result"]["status"], case["expected_status"], case)
        self.assertFalse(report["candidate_product_qualified"])

    def test_bad_namespace_is_not_prefix_presence_success(self) -> None:
        result = mod.qualify((mod.FIXTURES / "wrong-namespace.ttl").read_bytes(), self.expected, CANDIDATE)
        self.assertEqual(result["status"], "FAIL")
        failures = {item["id"] for item in result["assertions"] if item["status"] == "FAIL"}
        self.assertIn("DEFS-RESOLUTION", failures)
        self.assertIn("SAT-SP-CANDIDATES", failures)

    def test_pinned_defs_digest_is_checked_before_queries(self) -> None:
        real = mod.read_bounded
        def corrupt(path: Path, limit: int = mod.MAX_BYTES) -> bytes:
            data = real(path, limit)
            return data + b"\n# corruption\n" if path.name == "defs.ttl" else data
        with mock.patch.object(mod, "read_bounded", side_effect=corrupt):
            result = mod.qualify(self.model, self.expected, CANDIDATE)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["comparison_count"], 0)

    def test_missing_parser_is_blocked_and_not_a_green_empty_run(self) -> None:
        with mock.patch.object(mod, "rdf", side_effect=RuntimeError("dependency absent")):
            result = mod.qualify(self.model, self.expected, CANDIDATE)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["assertions_count"], 0)
        self.assertEqual(result["comparison_count"], 0)

    def test_empty_inventory_and_duplicate_case_ids_are_blocked(self) -> None:
        for mutation in ("empty", "duplicate", "no_selection", "unscoped"):
            expected = copy.deepcopy(self.expected)
            if mutation == "empty":
                expected["point_ids"] = []
            elif mutation == "duplicate":
                expected["selectors"].append(expected["selectors"][0])
            elif mutation == "no_selection":
                expected["selectors"][1]["selected_point"] = None
            else:
                expected["site"] = "RTU_01"
            with self.subTest(mutation=mutation):
                result = mod.qualify(self.model, expected, CANDIDATE)
                self.assertEqual(result["status"], "BLOCKED", result)

    def test_case_sensitive_defs_and_typed_values_survive_parse(self) -> None:
        graph = mod.parse_model(self.model)
        inventory = mod.graph_inventory(graph)
        self.assertEqual(inventory["site_count"], 2)
        self.assertEqual(inventory["equip_count"], 4)
        self.assertEqual(inventory["point_count"], 11)
        report = mod.qualify(self.model, self.expected, CANDIDATE)
        assertions = {item["id"]: item["status"] for item in report["assertions"]}
        for check in ("NUMBER-LITERAL", "BOOL-LITERAL", "STR-ENUM", "REF-VALUE"):
            self.assertEqual(assertions[check], "PASS")

    def test_reparent_to_dotted_equipment_uses_ref_and_preserves_opaque_key(self) -> None:
        lib = mod.rdf()
        graph = mod.parse_model(self.model)
        expected = copy.deepcopy(self.expected)
        case = copy.deepcopy(expected["selectors"][1])
        case["equipment"] = "urn:qa:equip/hp.2"
        case["expected_candidates"] = ["urn:qa:point/measured"]
        expected["selectors"] = [case]
        # The expected new parent is not satisfied by the old graph.
        before = mod.qualify(self.model, expected, CANDIDATE)
        self.assertEqual(before["status"], "FAIL")
        point = lib.URIRef("urn:qa:point/measured")
        equip_ref = lib.URIRef(mod.BASES["phIoT"] + "equipRef")
        graph.remove((point, equip_ref, None))
        graph.add((point, equip_ref, lib.URIRef(case["equipment"])))
        after = mod.qualify(graph.serialize(format="turtle").encode(), expected, CANDIDATE)
        self.assertEqual(after["status"], "PASS", after)
        self.assertEqual(after["selections"][0]["selected_point"], "urn:qa:point/measured")
        # No equipment.role string, dotted-name decoding or timeseries rename.
        self.assertEqual(case["series_key"], "opaque::8f6|unrelated-reader-key")

    def test_wrong_provider_and_remote_identity_fail_despite_correct_series_key(self) -> None:
        lib = mod.rdf()
        point = lib.URIRef("urn:qa:point/measured")
        for predicate in ("providerInstance", "remotePointId"):
            graph = mod.parse_model(self.model)
            relation = lib.URIRef(mod.OFDD + predicate)
            graph.remove((point, relation, None))
            graph.add((point, relation, lib.Literal("nonempty-but-wrong-source")))
            with self.subTest(predicate=predicate):
                report = mod.qualify(graph.serialize(format="turtle").encode(), self.expected, CANDIDATE)
                self.assertEqual(report["status"], "FAIL")
                failed = {item["id"] for item in report["assertions"] if item["status"] == "FAIL"}
                self.assertIn("SAT-APPROVED-OPAQUE-BINDING", failed)

    def test_ready_contract_without_independent_source_binding_is_blocked(self) -> None:
        for field in ("series_key", "provider_instance", "remote_point_id"):
            for value in (None, "", "  "):
                expected = copy.deepcopy(self.expected)
                if value is None:
                    del expected["selectors"][1][field]
                else:
                    expected["selectors"][1][field] = value
                with self.subTest(field=field, value=value):
                    report = mod.qualify(self.model, expected, CANDIDATE)
                    self.assertEqual(report["status"], "BLOCKED")
                    self.assertEqual(report["comparison_count"], 0)

    def test_turtle_links_are_not_fetched_and_query_terms_are_bound(self) -> None:
        import socket
        linked = self.model + b'\n<urn:qa:site/a> <http://www.w3.org/2002/07/owl#imports> <https://unreachable.invalid/defs> .\n'
        with mock.patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")):
            graph = mod.parse_model(linked)
        self.assertEqual(mod.graph_inventory(graph)["point_count"], 11)
        expected = copy.deepcopy(self.expected)
        expected["selectors"][0]["equipment"] = 'urn:qa:equip/RTU_01> } SERVICE <https://unreachable.invalid> {'
        result = mod.qualify(self.model, expected, CANDIDATE)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["comparison_count"], 0)

    def test_missing_control_and_changed_control_verdict_fail_closed(self) -> None:
        manifest = mod.load_json(mod.FIXTURES / "suite.json")
        real = mod.load_json
        for variant in ("drop", "greenwash"):
            changed = copy.deepcopy(manifest)
            if variant == "drop":
                changed["cases"].pop()
            else:
                changed["cases"][1]["expected_status"] = "PASS"
            with self.subTest(variant=variant), mock.patch.object(
                mod, "load_json", side_effect=lambda path: changed if path.name == "suite.json" else real(path)
            ):
                with self.assertRaises(ValueError):
                    mod.suite(CANDIDATE)

    def test_parser_rejects_oversize_input_without_parsing(self) -> None:
        with self.assertRaises(ValueError):
            mod.parse_model(b" " * (mod.MAX_BYTES + 1))

    def test_deadline_propagates_instead_of_continuing_controls(self) -> None:
        with mock.patch.object(mod, "load_defs", side_effect=TimeoutError("deadline")):
            with self.assertRaises(TimeoutError):
                mod.qualify(self.model, self.expected, CANDIDATE)

    def test_invalid_candidate_blocks_and_broken_cli_exits_nonzero(self) -> None:
        report = mod.qualify(self.model, self.expected, "latest")
        self.assertEqual(report["status"], "BLOCKED")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            proc = subprocess.run([sys.executable, str(SCRIPT), "model", "--candidate", CANDIDATE,
                                   "--model", str(mod.FIXTURES / "wrong-namespace.ttl"),
                                   "--expectations", str(mod.FIXTURES / "expected.json"),
                                   "--out", str(output)], capture_output=True, text=True, timeout=15)
            self.assertNotEqual(proc.returncode, 0)
            result = json.loads(output.read_text())
            self.assertEqual(result["status"], "FAIL")
            self.assertGreater(result["comparison_count"], 0)


if __name__ == "__main__":
    unittest.main()
