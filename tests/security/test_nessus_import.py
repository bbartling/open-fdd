"""Fail-closed credentialed Nessus report regressions."""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/security/nessus/import_nessus_report.py"
FIXTURES = ROOT / "scripts/security/nessus/fixtures"
SPEC = importlib.util.spec_from_file_location("import_nessus_report", MODULE_PATH)
nessus = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(nessus)


class NessusCredentialedEvidenceTest(unittest.TestCase):
    def assert_credentialed_rejected(self, fixture):
        measured = nessus.parse_nessus(FIXTURES / fixture)
        ok, reason = nessus.evaluate(
            measured, require_credentialed=True, allow_medium=False
        )
        self.assertFalse(ok, reason)

    def test_plugin_19506_no_is_rejected(self):
        self.assert_credentialed_rejected("not_credentialed_synthetic.nessus")

    def test_empty_report_host_is_unassessed_and_rejected(self):
        measured = nessus.parse_nessus(
            FIXTURES / "unassessed_host_synthetic.nessus"
        )
        ok, reason = nessus.evaluate(
            measured, require_credentialed=False, allow_medium=False
        )
        self.assertFalse(ok, reason)

    def test_every_host_must_have_positive_credentialed_evidence(self):
        self.assert_credentialed_rejected("partially_credentialed_synthetic.nessus")


if __name__ == "__main__":
    unittest.main()
