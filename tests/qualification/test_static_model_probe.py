"""Offline fail-closed contract tests for static_model_probe."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/qualification/semantic/static_model_probe.py"
SPEC = importlib.util.spec_from_file_location("static_model_probe", SCRIPT)
probe = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)


class StaticModelProbeTests(unittest.TestCase):
    def test_working_candidate_passes_equivalent_cases(self) -> None:
        def good(_ttl: str) -> dict[str, int]:
            return {"equipment": 1, "points": 1}

        result = probe.evaluate_cases(probe.DEFAULT_CASES, good)
        self.assertTrue(result["pass"], result)
        self.assertEqual(result["case_count"], len(probe.DEFAULT_CASES))
        self.assertTrue(all(case["rdf_isomorphic"] for case in result["cases"]))

    def test_dropped_point_mutation_fails(self) -> None:
        cases = [probe.DEFAULT_CASES[0]]

        def dropped(_ttl: str) -> dict[str, int]:
            return {"equipment": 1, "points": 0}

        result = probe.evaluate_cases(cases, dropped)
        self.assertFalse(result["pass"])
        self.assertEqual(result["cases"][0]["status"], "FAIL")

    def test_malformed_candidate_output_fails_closed(self) -> None:
        result = probe.evaluate_cases(probe.DEFAULT_CASES[:1], lambda _ttl: "not-json")
        self.assertFalse(result["pass"])
        self.assertIn("candidate output", result["cases"][0]["error"])

    def test_nonisomorphic_input_cannot_pass(self) -> None:
        changed = probe.BASE.replace('"Synthetic point"', '"Changed point"')
        cases = [probe.DEFAULT_CASES[0], {"name": "changed", "ttl": changed}]
        result = probe.evaluate_cases(cases, lambda _ttl: {"equipment": 1, "points": 1})
        self.assertFalse(result["pass"])
        self.assertFalse(result["cases"][1]["rdf_isomorphic"])

    def test_cli_writes_report_and_returns_mismatch_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "result.json"
            with mock.patch.object(
                probe, "parse_with_node", return_value={"equipment": 1, "points": 0}
            ), redirect_stdout(StringIO()):
                code = probe.main(["--json-out", str(out)])
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(out.read_text())["status"], "FAIL")

    def test_cli_success_code_with_working_candidate(self) -> None:
        with mock.patch.object(
            probe, "parse_with_node", return_value={"equipment": 1, "points": 1}
        ), redirect_stdout(StringIO()):
            self.assertEqual(probe.main([]), 0)

    def test_cli_setup_failure_returns_two(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cases = Path(tmp) / "empty.json"
            cases.write_text("[]", encoding="utf-8")
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                code = probe.main(["--cases", str(cases)])
            self.assertEqual(code, 2)

    def test_empty_cases_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least one case"):
            probe.evaluate_cases([], lambda _ttl: {"equipment": 1, "points": 1})


if __name__ == "__main__":
    unittest.main()
