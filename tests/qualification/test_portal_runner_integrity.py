"""Pure runner-integrity regressions for portal qualification PASS assertions."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QUAL = ROOT / "scripts" / "qualification"
sys.path.insert(0, str(QUAL / "portal"))

import portal_qual  # noqa: E402


class PortalRunnerCliIntegrityTest(unittest.TestCase):
    def run_cli(self, *args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-B", str(QUAL / "portal" / "portal_qual.py"), *args],
            input=input_text,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_identity_cli_rejects_added_tenant(self):
        result = self.run_cli(
            "validate-identity", "--role", "viewer", "--tenant-id", "tenant-a",
            input_text=json.dumps({"ok": True, "multi_tenant": True, "hub_admin": False, "role": "viewer", "tenant_ids": ["tenant-a", "tenant-b"]}),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exactly", result.stdout)

    def test_viewer_cli_fails_on_missing_or_duplicate_checks(self):
        checks = [
            {"check_id": cid, "status": "PASS"}
            for cid in sorted(portal_qual.VIEWER_WRITE_CHECK_IDS)
        ]
        with tempfile.TemporaryDirectory() as td:
            report = Path(td) / "security_report.json"
            report.write_text(json.dumps({"checks": checks}), encoding="utf-8")
            passed = self.run_cli("validate-viewer-write-matrix", "--report", str(report))
            self.assertEqual(passed.returncode, 0, passed.stdout + passed.stderr)
            report.write_text(json.dumps({"checks": checks[:-1]}), encoding="utf-8")
            missing = self.run_cli("validate-viewer-write-matrix", "--report", str(report))
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("missing:", missing.stdout)
            report.write_text(json.dumps({"checks": checks + [checks[0]]}), encoding="utf-8")
            duplicate = self.run_cli("validate-viewer-write-matrix", "--report", str(report))
            self.assertNotEqual(duplicate.returncode, 0)
            self.assertIn("duplicate:", duplicate.stdout)

    def test_viewer_cli_separates_agent_token_probe_without_weakening_matrix(self):
        required = [{"check_id": cid, "status": "PASS"}
                    for cid in sorted(portal_qual.VIEWER_WRITE_CHECK_IDS)]
        legacy = {"check_id": "y.authz.viewer_mutation_denied", "status": "PASS"}
        with tempfile.TemporaryDirectory() as td:
            report = Path(td) / "report.json"
            def evaluate(checks):
                report.write_text(json.dumps({"checks": checks}), encoding="utf-8")
                return self.run_cli("validate-viewer-write-matrix", "--report", str(report))
            passed = evaluate(required + [legacy])
            self.assertEqual(passed.returncode, 0, passed.stdout + passed.stderr)
            missing = evaluate(required[:-1] + [legacy])
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("missing:", missing.stdout)
            unknown = evaluate(required + [legacy, {"check_id": "y.authz.viewer_unknown_denied", "status": "PASS"}])
            self.assertNotEqual(unknown.returncode, 0)
            self.assertIn("unexpected:", unknown.stdout)
            blocked = evaluate(required[:-1] + [{**required[-1], "status": "BLOCKED"}, legacy])
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("not PASS:", blocked.stdout)

    def test_service_cli_requires_exact_names(self):
        exact = self.run_cli("validate-services", *sorted(portal_qual.REQUIRED_PORTAL_SERVICES))
        self.assertEqual(exact.returncode, 0, exact.stdout + exact.stderr)
        substring = self.run_cli(
            "validate-services", "central-api", "web", "timescale", "nf-emulator"
        )
        self.assertNotEqual(substring.returncode, 0)


if __name__ == "__main__":
    unittest.main()
