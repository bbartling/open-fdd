"""Offline regressions: the stress gate must fail closed (QA-01).

No live stack and no network: run_gate.py drives stub child scripts in a temp
directory, and gates 08/09 are exercised through their pure comparison helpers
with HTTP calls patched out.

Run: python3 -B -m unittest discover -s tests/qualification -v
"""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import textwrap
import unittest
from unittest import mock


STRESS = Path(__file__).resolve().parents[2] / "scripts/stress"
if str(STRESS) not in sys.path:
    sys.path.insert(0, str(STRESS))


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, STRESS / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


run_gate = _load("stress_run_gate", "run_gate.py")
gate08 = _load("stress_gate08", "08_sql_vs_pandas_sparql.py")
gate09 = _load("stress_gate09", "09_analytics_sql_vs_pandas.py")

REQUIRED = [
    "01_sparql_model.py",
    "03_sparql_zone_dataframe.py",
    "08_sql_vs_pandas_sparql.py",
    "09_analytics_sql_vs_pandas.py",
    "10_model_crud_helpers.py",
]

PASSING_CHILD = textwrap.dedent(
    """
    import json, os, sys
    with open(os.environ["OPENFDD_STRESS_RESULT_FILE"], "w") as fh:
        json.dump({"status": "PASS", "exit_code": 0}, fh)
    sys.exit(0)
    """
)
FAILING_CHILD = textwrap.dedent(
    """
    import json, os, sys
    with open(os.environ["OPENFDD_STRESS_RESULT_FILE"], "w") as fh:
        json.dump({"status": "FAIL", "exit_code": 1}, fh)
    sys.exit(1)
    """
)
SILENT_CHILD = "import sys\nsys.exit(0)\n"
LYING_CHILD = textwrap.dedent(
    """
    import json, os, sys
    with open(os.environ["OPENFDD_STRESS_RESULT_FILE"], "w") as fh:
        json.dump({"status": "BLOCKED", "exit_code": 2}, fh)
    sys.exit(0)
    """
)
HANGING_CHILD = "import time\ntime.sleep(30)\n"


class RunGateFailClosedTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        for script in REQUIRED:
            self.write(script, PASSING_CHILD)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, script, body):
        (self.dir / script).write_text(body, encoding="utf-8")

    def run_gate(self, *extra):
        summary = self.dir / "summary.json"
        argv = [
            "--base-url", "http://127.0.0.1:9",
            "--building-id", "SYNTH_UNIT",
            "--scripts-dir", str(self.dir),
            "--summary-json", str(summary),
            *extra,
        ]
        with contextlib.redirect_stdout(io.StringIO()):
            code = run_gate.main(argv)
        return code, json.loads(summary.read_text(encoding="utf-8"))

    def status_of(self, summary, script):
        return next(s["status"] for s in summary["steps"] if s["script"] == script)

    def test_all_required_steps_pass_is_the_only_pass(self):
        code, summary = self.run_gate()
        self.assertEqual(summary["verdict"], "PASS")
        self.assertEqual(code, 0)

    def test_crud_child_failure_fails_gate(self):
        self.write("10_model_crud_helpers.py", FAILING_CHILD)
        code, summary = self.run_gate()
        self.assertEqual(summary["verdict"], "FAIL")
        self.assertNotEqual(code, 0)
        self.assertEqual(self.status_of(summary, "10_model_crud_helpers.py"), "FAIL")

    def test_removed_required_step_is_not_pass(self):
        for script in REQUIRED:
            with self.subTest(removed=script):
                for other in REQUIRED:
                    self.write(other, PASSING_CHILD)
                (self.dir / script).unlink()
                code, summary = self.run_gate()
                self.assertNotEqual(summary["verdict"], "PASS")
                self.assertNotEqual(code, 0)
                self.assertEqual(self.status_of(summary, script), "BLOCKED")

    def test_missing_result_file_is_not_pass(self):
        self.write("09_analytics_sql_vs_pandas.py", SILENT_CHILD)
        code, summary = self.run_gate()
        self.assertEqual(summary["verdict"], "BLOCKED")
        self.assertNotEqual(code, 0)

    def test_result_file_contradicting_exit_zero_fails(self):
        self.write("08_sql_vs_pandas_sparql.py", LYING_CHILD)
        code, summary = self.run_gate()
        self.assertEqual(summary["verdict"], "FAIL")
        self.assertNotEqual(code, 0)

    def test_child_blocked_exit_is_blocked(self):
        self.write("09_analytics_sql_vs_pandas.py", "import sys\nsys.exit(2)\n")
        code, summary = self.run_gate()
        self.assertEqual(summary["verdict"], "BLOCKED")
        self.assertEqual(code, 2)

    def test_timeout_fails_gate(self):
        self.write("01_sparql_model.py", HANGING_CHILD)
        code, summary = self.run_gate("--step-timeout", "1")
        self.assertEqual(summary["verdict"], "FAIL")
        self.assertNotEqual(code, 0)
        self.assertIn("timed out", summary["steps"][0]["detail"])

    def test_skipping_required_step_is_not_pass(self):
        code, summary = self.run_gate("--skip-analytics")
        self.assertEqual(summary["verdict"], "BLOCKED")
        self.assertNotEqual(code, 0)

    def test_present_optional_step_failure_fails_gate(self):
        self.write("02_sparql_fc1_points.py", FAILING_CHILD)
        code, summary = self.run_gate()
        self.assertEqual(summary["verdict"], "FAIL")
        self.assertNotEqual(code, 0)

    def test_absent_optional_steps_are_reported_not_landed(self):
        _, summary = self.run_gate()
        self.assertEqual(self.status_of(summary, "02_sparql_fc1_points.py"), "NOT_LANDED")

    def test_empty_plan_is_not_pass(self):
        report = run_gate.GateReport()
        self.assertEqual(report.verdict, "BLOCKED")
        self.assertNotEqual(report.exit_code, 0)


class RunChildResultFileTest(unittest.TestCase):
    def run_child(self, main):
        helpers = sys.modules["helpers"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.json"
            with mock.patch.dict("os.environ", {helpers.RESULT_FILE_ENV: str(path)}):
                with contextlib.redirect_stderr(io.StringIO()):
                    code = helpers.run_child(main, "unit.py")
            return code, json.loads(path.read_text(encoding="utf-8"))

    def test_system_exit_message_records_fail(self):
        def main():
            raise SystemExit("building_id required")

        code, body = self.run_child(main)
        self.assertEqual(code, 1)
        self.assertEqual(body["status"], "FAIL")

    def test_blocked_and_pass_codes_recorded(self):
        self.assertEqual(self.run_child(lambda: 2)[1]["status"], "BLOCKED")
        self.assertEqual(self.run_child(lambda: 0)[1]["status"], "PASS")


class Gate08IdentityTest(unittest.TestCase):
    def test_wrong_equipment_with_identical_fault_hours_fails(self):
        results = [{"rule_id": "FC1", "equipment_id": "AHU_2", "fault_hours": 3.25}]
        status, _, msg = gate08.compare_sql_to_oracle(results, "FC1", "AHU_1", 3.25)
        self.assertEqual(status, "FAIL")
        self.assertIn("AHU_1", msg)

    def test_prefix_equipment_id_is_not_identity(self):
        results = [{"rule_id": "FC1", "equipment_id": "RTU_010", "fault_hours": 1.0}]
        status, _, _ = gate08.compare_sql_to_oracle(results, "FC1", "RTU_01", 1.0)
        self.assertEqual(status, "FAIL")

    def test_wrong_rule_on_right_equipment_fails(self):
        results = [{"rule_id": "AHU-DUCTHI", "equipment_id": "AHU_1", "fault_hours": 2.0}]
        status, _, _ = gate08.compare_sql_to_oracle(results, "FC1", "AHU_1", 2.0)
        self.assertEqual(status, "FAIL")

    def test_duplicate_identity_rows_fail(self):
        row = {"rule_id": "FC1", "equipment_id": "AHU_1", "fault_hours": 2.0}
        status, _, _ = gate08.compare_sql_to_oracle([row, dict(row)], "FC1", "AHU_1", 2.0)
        self.assertEqual(status, "FAIL")

    def test_missing_fault_hours_is_not_zero(self):
        results = [{"rule_id": "FC1", "equipment_id": "AHU_1", "fault_hours": None}]
        status, _, _ = gate08.compare_sql_to_oracle(results, "FC1", "AHU_1", 0.0)
        self.assertEqual(status, "FAIL")

    def test_zero_result_rows_blocked(self):
        status, _, _ = gate08.compare_sql_to_oracle([], "FC1", "AHU_1", 0.0)
        self.assertEqual(status, "BLOCKED")

    def test_exact_identity_within_tolerance_passes(self):
        results = [
            {"rule_id": "FC1", "equipment_id": "AHU_2", "fault_hours": 9.0},
            {"rule_id": "FC1", "equipment_id": "AHU_1", "fault_hours": 3.26},
        ]
        status, s_hours, _ = gate08.compare_sql_to_oracle(results, "FC1", "AHU_1", 3.25)
        self.assertEqual(status, "PASS")
        self.assertEqual(s_hours, 3.26)

    def test_role_points_keep_only_exact_equipment(self):
        rows = [
            {"equipmentId": "RTU_01", "column": "sat"},
            {"equipmentId": "RTU_010", "column": "sat"},
            {"equipmentId": "AHU_2", "column": "duct_static"},
        ]
        with mock.patch.object(gate08, "post_sparql", return_value=rows):
            got = gate08._role_points(None, {}, "SYNTH_UNIT", "RTU_01")
        self.assertEqual([r["equipmentId"] for r in got], ["RTU_01"])

    def test_zero_min_rules_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as ctx:
            gate08.main(["--building-id", "SYNTH_UNIT", "--min-rules", "0"])
        self.assertNotEqual(ctx.exception.code, 0)


class Gate09ZeroComparisonsTest(unittest.TestCase):
    def check_economizer(self, body, minimum=1):
        with mock.patch.object(gate09, "analytics_post", return_value=body):
            with contextlib.redirect_stdout(io.StringIO()):
                return gate09._check_economizer(None, {}, "SYNTH_UNIT", minimum=minimum)

    def test_empty_points_blocked(self):
        self.assertEqual(self.check_economizer({"ok": True, "points": []}), 2)

    def test_unavailable_analytics_blocked(self):
        self.assertEqual(self.check_economizer({"ok": False, "error": "no roles"}), 2)

    def test_points_without_comparable_fields_blocked(self):
        body = {"points": [{"oat_f": 50.0}, {"rat_f": 70.0, "delta_or_f": 1.0}]}
        self.assertEqual(self.check_economizer(body), 2)

    def test_fewer_than_declared_comparisons_blocked(self):
        pt = {"oat_f": 50.0, "rat_f": 70.0, "mat_f": 60.0, "delta_or_f": -20.0, "delta_mr_f": -10.0}
        self.assertEqual(self.check_economizer({"points": [pt]}, minimum=2), 2)
        self.assertEqual(self.check_economizer({"points": [pt, dict(pt)]}, minimum=2), 0)

    def test_zero_valued_temperatures_are_compared(self):
        pt = {"oat_f": 0.0, "rat_f": 0.0, "mat_f": 0.0, "delta_or_f": 0.0, "delta_mr_f": 0.0}
        self.assertEqual(self.check_economizer({"points": [pt]}), 0)

    def test_divergent_delta_fails(self):
        pt = {"oat_f": 50.0, "rat_f": 70.0, "mat_f": 60.0, "delta_or_f": -19.0, "delta_mr_f": -10.0}
        self.assertEqual(self.check_economizer({"points": [pt]}), 1)

    def test_comfort_with_no_rows_blocked(self):
        with mock.patch.object(gate09, "analytics_post", return_value={"rows": []}):
            with contextlib.redirect_stdout(io.StringIO()):
                code = gate09._check_comfort(None, {}, "SYNTH_UNIT", minimum=1)
        self.assertEqual(code, 2)

    def test_combine_never_passes_blocked_or_empty(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(gate09.combine([0, 2]), 2)
            self.assertEqual(gate09.combine([]), 2)
            self.assertEqual(gate09.combine([2, 1]), 1)
            self.assertEqual(gate09.combine([0, 0]), 0)

    def test_zero_minimum_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as ctx:
            gate09.main(["--building-id", "SYNTH_UNIT", "--min-economizer-points", "0"])
        self.assertNotEqual(ctx.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
