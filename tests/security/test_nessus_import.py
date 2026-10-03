"""Fail-closed credentialed Nessus report regressions."""
from __future__ import annotations

import datetime as dt
import importlib.util
import tempfile
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
    def assert_credentialed_rejected(self, fixture: str) -> None:
        measured = nessus.parse_nessus(FIXTURES / fixture)
        ok, reason = nessus.evaluate(
            measured, require_credentialed=True, allow_medium=False
        )
        self.assertFalse(ok, reason)

    def test_plugin_19506_no_is_rejected(self) -> None:
        self.assert_credentialed_rejected("not_credentialed_synthetic.nessus")

    def test_empty_report_host_is_unassessed_and_rejected(self) -> None:
        measured = nessus.parse_nessus(
            FIXTURES / "unassessed_host_synthetic.nessus"
        )
        ok, reason = nessus.evaluate(
            measured, require_credentialed=False, allow_medium=False
        )
        self.assertFalse(ok, reason)

    def test_every_host_must_have_positive_credentialed_evidence(self) -> None:
        self.assert_credentialed_rejected("partially_credentialed_synthetic.nessus")


class NessusImporterHardeningTest(unittest.TestCase):
    def test_rejects_dtd_and_entity_declarations(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".nessus", delete=False) as handle:
            handle.write(
                b'<?xml version="1.0"?>'
                b"<!DOCTYPE foo [<!ENTITY xxe \"test\">]>"
                b"<NessusClientData_v2></NessusClientData_v2>"
            )
            path = Path(handle.name)
        try:
            with self.assertRaises(SystemExit):
                nessus.parse_nessus(path)
        finally:
            path.unlink(missing_ok=True)

    def test_host_and_item_bounds(self) -> None:
        original_hosts = nessus.MAX_HOSTS
        original_items = nessus.MAX_ITEMS
        try:
            nessus.MAX_HOSTS = 1
            nessus.MAX_ITEMS = 100
            xml = b"""<?xml version="1.0"?>
<NessusClientData_v2>
  <Report name="bound">
    <ReportHost name="192.0.2.1"><ReportItem severity="0" pluginID="1"/></ReportHost>
    <ReportHost name="192.0.2.2"><ReportItem severity="0" pluginID="2"/></ReportHost>
  </Report>
</NessusClientData_v2>"""
            with tempfile.NamedTemporaryFile(suffix=".nessus", delete=False) as handle:
                handle.write(xml)
                path = Path(handle.name)
            try:
                with self.assertRaises(SystemExit):
                    nessus.parse_nessus(path)
            finally:
                path.unlink(missing_ok=True)

            nessus.MAX_HOSTS = 8
            nessus.MAX_ITEMS = 1
            xml_items = b"""<?xml version="1.0"?>
<NessusClientData_v2>
  <Report name="bound">
    <ReportHost name="192.0.2.3">
      <ReportItem severity="0" pluginID="1"/>
      <ReportItem severity="0" pluginID="2"/>
    </ReportHost>
  </Report>
</NessusClientData_v2>"""
            with tempfile.NamedTemporaryFile(suffix=".nessus", delete=False) as handle:
                handle.write(xml_items)
                path = Path(handle.name)
            try:
                with self.assertRaises(SystemExit):
                    nessus.parse_nessus(path)
            finally:
                path.unlink(missing_ok=True)
        finally:
            nessus.MAX_HOSTS = original_hosts
            nessus.MAX_ITEMS = original_items

    def test_allow_medium_requires_exact_dispositions(self) -> None:
        measured = nessus.parse_nessus(FIXTURES / "medium_synthetic.nessus")
        ok, reason = nessus.evaluate(
            measured, require_credentialed=False, allow_medium=True
        )
        self.assertFalse(ok)
        self.assertIn("disposition", reason)

        ok, reason = nessus.evaluate(
            measured,
            require_credentialed=False,
            allow_medium=True,
            medium_dispositions=[
                {
                    "plugin_id": "88888",
                    "host": "192.0.2.12",
                    "port": "8080",
                    "owner": "security",
                    "rationale": "lab-only synthetic acceptance",
                    "expires_at": "2030-01-01T00:00:00Z",
                    "retest_after": "2030-01-15T00:00:00Z",
                }
            ],
        )
        self.assertTrue(ok, reason)

    def test_medium_disposition_omitting_host_or_port_rejected(self) -> None:
        measured = nessus.parse_nessus(FIXTURES / "medium_synthetic.nessus")
        ok, reason = nessus.evaluate(
            measured,
            require_credentialed=False,
            allow_medium=True,
            medium_dispositions=[
                {
                    "plugin_id": "88888",
                    "owner": "security",
                    "rationale": "too broad",
                    "expires_at": "2030-01-01T00:00:00Z",
                    "retest_after": "2030-01-15T00:00:00Z",
                }
            ],
        )
        self.assertFalse(ok)
        self.assertTrue("unmatched" in reason or "missing" in reason)

    def test_invalid_candidate_sha_errors_not_skipped(self) -> None:
        measured = nessus.parse_nessus(FIXTURES / "expectation_bound_synthetic.nessus")
        now = dt.datetime(2026, 10, 3, 14, 0, tzinfo=dt.timezone.utc)
        expectation = {
            "schema_version": nessus.EXPECTATION_SCHEMA_VERSION,
            "expected_targets": ["192.0.2.20"],
            "candidate_sha256": "invalid",
            "policy_name": "openfdd-ot-lab",
            "feed_version": "202610030001",
            "max_age_seconds": 6 * 60 * 60,
            "require_scan_complete": True,
        }
        ok, reason = nessus.evaluate(
            measured,
            require_credentialed=True,
            allow_medium=False,
            expectation=expectation,
            now=now,
        )
        self.assertFalse(ok)
        self.assertIn("invalid candidate_sha256", reason)

    def test_expectation_manifest_binds_targets_and_freshness(self) -> None:
        measured = nessus.parse_nessus(FIXTURES / "expectation_bound_synthetic.nessus")
        now = dt.datetime(2026, 10, 3, 14, 0, tzinfo=dt.timezone.utc)
        expectation = {
            "schema_version": nessus.EXPECTATION_SCHEMA_VERSION,
            "expected_targets": ["192.0.2.20"],
            "candidate_sha256": "a" * 64,
            "policy_name": "openfdd-ot-lab",
            "feed_version": "202610030001",
            "max_age_seconds": 6 * 60 * 60,
            "require_scan_complete": True,
            "report_names": ["openfdd-synthetic-bound"],
        }
        ok, reason = nessus.evaluate(
            measured,
            require_credentialed=True,
            allow_medium=False,
            expectation=expectation,
            now=now,
        )
        self.assertTrue(ok, reason)

        foreign_expectation = dict(expectation)
        foreign_expectation["expected_targets"] = ["192.0.2.99"]
        ok, reason = nessus.evaluate(
            measured,
            require_credentialed=True,
            allow_medium=False,
            expectation=foreign_expectation,
            now=now,
        )
        self.assertFalse(ok)
        self.assertIn("missing from scan", reason)

        stale_now = dt.datetime(2026, 10, 10, 0, 0, tzinfo=dt.timezone.utc)
        ok, reason = nessus.evaluate(
            measured,
            require_credentialed=True,
            allow_medium=False,
            expectation=expectation,
            now=stale_now,
        )
        self.assertFalse(ok)
        self.assertIn("max_age_seconds", reason)


if __name__ == "__main__":
    unittest.main()
