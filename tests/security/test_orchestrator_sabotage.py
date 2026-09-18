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


if __name__ == "__main__":
    unittest.main()
