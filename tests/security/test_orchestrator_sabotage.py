"""Orchestrator sabotage stubs — never contact Railway or start containers."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/security"))
sys.path.insert(0, str(ROOT / "scripts/qualification"))

from openfdd_security.evidence import (  # noqa: E402
    CheckResult,
    SecurityReport,
    reconcile_child_rc,
    validate_report_for_qualification,
    write_report,
)

# Load write_manifest without package install
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "write_manifest", ROOT / "scripts/qualification/write_manifest.py"
)
wm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wm)


def _valid_report(td: Path, **overrides) -> Path:
    report = SecurityReport(
        profile="isolated_full",
        executed=True,
        dry_run=False,
        full_profile=True,
        suites=["X", "Y", "Z"],
    )
    for k, v in overrides.items():
        setattr(report, k, v)
    report.add(CheckResult(check_id="a", suite="X", title="a", status="PASS"))
    report.add(CheckResult(check_id="b", suite="Y", title="b", status="PASS"))
    write_report(report, td)
    return td / "security_report.json"


class OrchestratorSabotageTest(unittest.TestCase):
    def test_missing_report_not_qualified(self):
        with tempfile.TemporaryDirectory() as td:
            ok, reason = validate_report_for_qualification(
                Path(td) / "missing.json",
                expected_profile="isolated_full",
            )
            self.assertFalse(ok)
            self.assertIn("missing", reason)

    def test_dry_run_artifact_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p = _valid_report(Path(td), executed=False, dry_run=True)
            # rewrite properly
            report = SecurityReport(
                profile="isolated_full", executed=False, dry_run=True, full_profile=True
            )
            report.add(CheckResult(check_id="a", suite="X", title="a", status="SKIPPED"))
            write_report(report, Path(td))
            ok, reason = validate_report_for_qualification(
                Path(td) / "security_report.json",
                expected_profile="isolated_full",
            )
            self.assertFalse(ok)
            self.assertIn("dry-run", reason)

    def test_hash_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p = _valid_report(Path(td))
            ok, _ = validate_report_for_qualification(
                p, expected_profile="isolated_full", expected_sha256="deadbeef"
            )
            self.assertFalse(ok)

    def test_zero_checks_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            report = SecurityReport(
                profile="isolated_full", executed=True, dry_run=False, full_profile=True
            )
            write_report(report, Path(td))
            ok, reason = validate_report_for_qualification(
                Path(td) / "security_report.json",
                expected_profile="isolated_full",
            )
            self.assertFalse(ok)

    def test_wrong_profile_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p = _valid_report(Path(td))
            ok, reason = validate_report_for_qualification(
                p, expected_profile="live_readonly"
            )
            self.assertFalse(ok)
            self.assertIn("profile", reason)

    def test_subset_full_profile_false_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p = _valid_report(Path(td), full_profile=False)
            ok, reason = validate_report_for_qualification(
                p, expected_profile="isolated_full", require_full_profile=True
            )
            self.assertFalse(ok)

    def test_exit0_missing_report_gate_stub(self):
        """Simulate child exit 0 without writing report → qualification ERROR."""
        with tempfile.TemporaryDirectory() as td:
            art = Path(td)
            # Fake gate: exit 0, no report
            stub = art / "fake_gate.sh"
            stub.write_text("#!/bin/sh\nexit 0\n")
            stub.chmod(0o755)
            rc = subprocess.call(["bash", str(stub)])
            self.assertEqual(rc, 0)
            report = art / "security_report.json"
            self.assertFalse(report.is_file())
            m = wm.new_manifest(
                run_id="sabotage",
                environment_class="unit",
                hub_base="http://127.0.0.1",
                candidate_sha="abc",
                harness_sha="def",
                required_gates=["25_security_python_harness"],
            )
            # Runner that only maps exit→PASS would falsely qualify; we require report.
            wm.record_gate(
                m,
                "25_security_python_harness",
                "ERROR",
                failure_reason="exit=0 but missing security_report.json",
            )
            wm.finalize(m)
            self.assertFalse(m["overall"]["fully_qualified"])

    def test_all_na_security_not_qualified(self):
        m = wm.new_manifest(
            run_id="na",
            environment_class="unit",
            hub_base="http://127.0.0.1",
            candidate_sha=None,
            harness_sha=None,
            required_gates=["25_security_python_harness", "25b_security_post_stress"],
        )
        wm.record_gate(
            m,
            "25_security_python_harness",
            "NOT_APPLICABLE",
            failure_reason="no fixtures",
        )
        wm.record_gate(
            m,
            "25b_security_post_stress",
            "NOT_APPLICABLE",
            failure_reason="no fixtures",
        )
        wm.finalize(m)
        self.assertFalse(m["overall"]["fully_qualified"])

    def test_dropped_required_suite_blocks(self):
        m = wm.new_manifest(
            run_id="drop",
            environment_class="unit",
            hub_base="http://127.0.0.1",
            candidate_sha=None,
            harness_sha=None,
            required_gates=[
                "25_security_python_harness",
                "25b_security_post_stress",
                "26_security_mqtt_acl",
            ],
        )
        wm.record_gate(m, "25_security_python_harness", "PASS")
        wm.record_gate(m, "25b_security_post_stress", "PASS")
        # 26 never recorded → ERROR
        wm.finalize(m)
        self.assertEqual(m["gates"]["26_security_mqtt_acl"]["status"], "ERROR")
        self.assertFalse(m["overall"]["fully_qualified"])

    def test_valid_complete_run_qualifies(self):
        with tempfile.TemporaryDirectory() as td:
            p = _valid_report(Path(td))
            meta = json.loads((Path(td) / "security_report.sha256").read_text())
            ok, reason = validate_report_for_qualification(
                p,
                expected_profile="isolated_full",
                expected_sha256=meta["sha256"],
            )
            self.assertTrue(ok, reason)
            m = wm.new_manifest(
                run_id="ok",
                environment_class="unit",
                hub_base="http://127.0.0.1",
                candidate_sha=None,
                harness_sha=None,
                required_gates=["25_security_python_harness"],
            )
            wm.record_gate(
                m,
                "25_security_python_harness",
                "PASS",
                artifact_paths=[str(p)],
            )
            wm.finalize(m)
            self.assertTrue(m["overall"]["fully_qualified"])

    def test_fail_report_with_exit0_not_qualified(self):
        with tempfile.TemporaryDirectory() as td:
            report = SecurityReport(
                profile="isolated_full", executed=True, dry_run=False, full_profile=True
            )
            report.add(CheckResult(check_id="a", suite="X", title="a", status="FAIL"))
            write_report(report, Path(td))
            ok, _ = validate_report_for_qualification(
                Path(td) / "security_report.json",
                expected_profile="isolated_full",
            )
            self.assertFalse(ok)

    def test_r01_string_bool_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p = _valid_report(Path(td))
            data = json.loads(p.read_text())
            data["executed"] = "true"
            data["dry_run"] = "false"
            p.write_text(json.dumps(data))
            ok, reason = validate_report_for_qualification(
                p, expected_profile="isolated_full"
            )
            self.assertFalse(ok)
            self.assertIn("boolean", reason)

    def test_r01_contradictory_counts_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p = _valid_report(Path(td))
            data = json.loads(p.read_text())
            data["counts"] = {
                "planned": 2,
                "pass": 99,
                "fail": 0,
                "error": 0,
                "blocked": 0,
                "skipped": 0,
                "not_applicable": 0,
            }
            p.write_text(json.dumps(data))
            ok, reason = validate_report_for_qualification(
                p, expected_profile="isolated_full"
            )
            self.assertFalse(ok)
            self.assertIn("counts", reason)

    def test_r01_invented_pass_missing_required_ids(self):
        with tempfile.TemporaryDirectory() as td:
            p = _valid_report(Path(td))
            ok, reason = validate_report_for_qualification(
                p,
                expected_profile="isolated_full",
                required_check_ids=["z.auth.admin_login", "z.auth.operator_login"],
            )
            self.assertFalse(ok)
            self.assertIn("missing required", reason)

    def test_r01_pass_plus_skipped_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            report = SecurityReport(
                profile="isolated_full",
                executed=True,
                dry_run=False,
                full_profile=True,
            )
            report.add(CheckResult(check_id="a", suite="X", title="a", status="PASS"))
            report.add(CheckResult(check_id="b", suite="Y", title="b", status="SKIPPED"))
            write_report(report, Path(td))
            ok, reason = validate_report_for_qualification(
                Path(td) / "security_report.json",
                expected_profile="isolated_full",
            )
            self.assertFalse(ok)
            self.assertIn("skipped", reason.lower())

    def test_r01_candidate_sha_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            p = _valid_report(Path(td))
            data = json.loads(p.read_text())
            data["candidate"] = {"sha": "abc123"}
            p.write_text(json.dumps(data))
            ok, reason = validate_report_for_qualification(
                p,
                expected_profile="isolated_full",
                expected_candidate_sha="deadbeef",
            )
            self.assertFalse(ok)
            self.assertIn("candidate", reason)

    def test_r02_mixed_pass_blocked_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "security_report.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "openfdd_security_report_v1",
                        "profile": "live_readonly",
                        "executed": True,
                        "dry_run": False,
                        "full_profile": False,
                        "overall_status": "BLOCKED",
                        "fully_qualified": False,
                        "counts": {
                            "planned": 2,
                            "pass": 1,
                            "fail": 0,
                            "error": 0,
                            "blocked": 1,
                            "skipped": 0,
                            "not_applicable": 0,
                        },
                        "checks": [
                            {
                                "check_id": "a",
                                "suite": "X",
                                "status": "PASS",
                                "title": "a",
                            },
                            {
                                "check_id": "b",
                                "suite": "Y",
                                "status": "BLOCKED",
                                "title": "b",
                            },
                        ],
                    }
                )
            )
            ok, reason = validate_report_for_qualification(
                path,
                expected_profile="live_readonly",
                require_full_profile=False,
                postcheck=True,
            )
            self.assertFalse(ok)
            self.assertIn("blocked", reason.lower())

    def test_r02_child_rc_contradicts_report_ok(self):
        with tempfile.TemporaryDirectory() as td:
            p = _valid_report(Path(td))
            ok, reason = validate_report_for_qualification(
                p,
                expected_profile="isolated_full",
                child_rc=1,
            )
            self.assertFalse(ok)
            self.assertIn("child_rc", reason)
            ok2, status, _ = reconcile_child_rc(
                report_ok=True, report_status="PASS", child_rc=5
            )
            self.assertFalse(ok2)
            self.assertEqual(status, "ERROR")

    def test_r02_gate25_wrapper_rejects_stale_pass_with_failed_rc(self):
        """Stub gate 25 validator path: report PASS + child_rc!=0 → ERROR."""
        with tempfile.TemporaryDirectory() as td:
            art = Path(td)
            report_dir = art / "python_harness"
            report_dir.mkdir()
            p = _valid_report(report_dir)
            # Minimal reproduction of gate 25 reconcile predicate.
            ok, reason = validate_report_for_qualification(
                p,
                expected_profile="isolated_full",
                child_rc=5,
            )
            self.assertFalse(ok)
            ok2, status, reason2 = reconcile_child_rc(
                report_ok=True, report_status="PASS", child_rc=5
            )
            self.assertFalse(ok2)
            self.assertEqual(status, "ERROR")
            self.assertIn("contradictory", reason2)

    def test_r02_mqtt_gate26_prefers_child_rc(self):
        """Gate 26 must ERROR when observer JSON says PASS but process rc!=0."""
        with tempfile.TemporaryDirectory() as td:
            art = Path(td)
            verdict = art / "mqtt_acl_verdict.json"
            verdict.write_text(json.dumps({"ok": True, "status": "PASS"}))
            gate = art / "gate26_stub.sh"
            gate.write_text(
                """#!/usr/bin/env bash
set -euo pipefail
ART="$1"
rc=5
obs_status=$(jq -r '.status // empty' "$ART/mqtt_acl_verdict.json")
obs_ok_bool=$(jq -r 'if .ok == true then "true" else "false" end' "$ART/mqtt_acl_verdict.json")
if [[ "$obs_ok_bool" == "true" && "$obs_status" == "PASS" && "$rc" -eq 0 ]]; then
  exit 0
fi
if [[ "$obs_ok_bool" == "true" && "$obs_status" == "PASS" && "$rc" -ne 0 ]]; then
  echo '{"ok":false,"status":"ERROR","reason":"observer PASS but child_rc!=0 (contradictory)"}' \
    >"$ART/security_gate_verdict.json"
  exit 2
fi
exit "$rc"
"""
            )
            gate.chmod(0o755)
            completed = subprocess.run(
                ["bash", str(gate), str(art)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 2)
            out = json.loads((art / "security_gate_verdict.json").read_text())
            self.assertEqual(out["status"], "ERROR")
            self.assertFalse(out["ok"])


if __name__ == "__main__":
    unittest.main()
