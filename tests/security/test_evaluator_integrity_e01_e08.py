"""Wave U U1 — permanent regressions for audit cases E01–E08.

Offline only: synthetic HTTP, no sockets/credentials. Exit failure means a
false-PASS detector remains. Converted from the private 2026-09-20 audit
reproducer (Documents path is not a runtime dependency).
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
import sys

sys.path.insert(0, str(ROOT / "scripts/security"))

from openfdd_security import SCHEMA_VERSION  # noqa: E402
from openfdd_security.config import FixtureRefs, ProbeConfig  # noqa: E402
from openfdd_security.evidence import (  # noqa: E402
    CheckResult,
    SecurityReport,
    validate_report_for_qualification,
)
from openfdd_security.suites import SuiteContext, run_suite_y  # noqa: E402
from openfdd_security.transport import Response  # noqa: E402


class SyntheticClient:
    def __init__(self, fx: FixtureRefs):
        self.fx = fx

    def request(self, method, path, *, token=None, **kwargs):
        status, body = 200, b"{}"
        if method == "POST":
            status, body = 401, b'{"ok":false}'
        elif path.startswith("/api/admin/"):
            status, body = 403, b'{"ok":false}'
        elif path.startswith("/api/auth/me"):
            # Viewer path used by E07 identity confirm
            if token == "fixture-only-viewer":
                body = b'{"role":"viewer","sub":"viewer"}'
            elif token == "fixture-only-a":
                body = b'{"role":"operator","sub":"acme-ops"}'
            elif token == "fixture-only-b":
                body = b'{"role":"operator","sub":"b100-ops"}'
            else:
                body = b'{"role":"operator","sub":"x"}'
        elif f"building_id={self.fx.building_b}" in path and token == "fixture-only-a":
            status, body = 403, b'{"ok":false}'
        elif f"building_id={self.fx.building_a}" in path and token == "fixture-only-b":
            status = 403
            body = json.dumps(
                {"ok": False, "detail": self.fx.canary_a}
            ).encode()
        return Response(
            status,
            {"Content-Type": "application/json"},
            body,
            0,
            "http://fixture.invalid",
        )


class EvaluatorIntegrityTests(unittest.TestCase):
    def test_e01_all_skipped_cannot_fully_qualify(self) -> None:
        report = SecurityReport(profile="live_readonly", executed=True, dry_run=False)
        report.add(CheckResult("synthetic.skipped", "Y", "SKIPPED", "synthetic"))
        report.reconcile()
        self.assertFalse(report.fully_qualified)
        self.assertEqual(report.overall_status, "BLOCKED")

    def test_e02_validator_rejects_empty_checks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="openfdd-e02-") as temp:
            path = Path(temp) / "security_report.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "profile": "live_readonly",
                        "executed": True,
                        "dry_run": False,
                        "full_profile": True,
                        "overall_status": "PASS",
                        "fully_qualified": True,
                        "counts": {"planned": 1, "pass": 1},
                        "checks": [],
                    }
                ),
                encoding="utf-8",
            )
            accepted, reason = validate_report_for_qualification(
                path, expected_profile="live_readonly"
            )
            self.assertFalse(accepted)
            self.assertIn("empty", reason.lower())

    def test_e03_postcheck_rejects_all_blocked(self) -> None:
        with tempfile.TemporaryDirectory(prefix="openfdd-e03-") as temp:
            path = Path(temp) / "security_report.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "profile": "live_readonly",
                        "executed": True,
                        "dry_run": False,
                        "full_profile": False,
                        "overall_status": "BLOCKED",
                        "fully_qualified": False,
                        "counts": {
                            "planned": 3,
                            "blocked": 3,
                            "pass": 0,
                            "fail": 0,
                        },
                        "checks": [
                            {
                                "check_id": f"b{i}",
                                "suite": "Y",
                                "status": "BLOCKED",
                                "title": "x",
                            }
                            for i in range(3)
                        ],
                    }
                ),
                encoding="utf-8",
            )
            accepted, reason = validate_report_for_qualification(
                path,
                expected_profile="live_readonly",
                require_full_profile=False,
                postcheck=True,
            )
            self.assertFalse(accepted)
            self.assertTrue(
                "zero PASS" in reason or "BLOCKED" in reason or "blocked" in reason.lower()
            )

    def test_e04_e07_suite_y_detectors(self) -> None:
        fx = FixtureRefs()
        cfg = ProbeConfig(raw={}, origin_allowlist=[], identities={}, fixtures=fx)
        results = []
        ctx = SuiteContext(
            SyntheticClient(fx),
            cfg,
            "live_readonly",
            results.append,
            tokens={
                "operator_a": "fixture-only-a",
                "operator_b": "fixture-only-b",
                "viewer_a": "fixture-only-viewer",
            },
        )
        run_suite_y(ctx)
        by_id = {c.check_id: c for c in results}
        self.assertNotEqual(
            by_id["y.authz.a_own_building_control"].status,
            "PASS",
            "E04: empty {} must not PASS own control",
        )
        self.assertNotEqual(
            by_id["y.authz.b_own_building_control"].status,
            "PASS",
            "E05: empty {} must not PASS B own control",
        )
        self.assertNotEqual(
            by_id["y.authz.b_foreign_building_denied"].status,
            "PASS",
            "E06: canary in 403 body must not PASS",
        )
        self.assertNotEqual(
            by_id["y.authz.viewer_mutation_denied"].status,
            "PASS",
            "E07: 401 must not prove viewer role denial",
        )


class ZapEmptySiteTests(unittest.TestCase):
    def test_e08_empty_site_rejected(self) -> None:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "zap_baseline_verdict",
            ROOT / "scripts/qualification/zap_baseline_verdict.py",
        )
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        with tempfile.TemporaryDirectory(prefix="openfdd-e08-") as temp:
            path = Path(temp) / "empty-zap-report.json"
            path.write_text('{"site": []}', encoding="utf-8")
            rc = mod.main(["--report", str(path)])
            self.assertNotEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
