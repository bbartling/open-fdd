"""Astra C-PY: bounded matrix + SSRF policy offline tests."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "security"))

from bounded_matrix import selftest as matrix_selftest  # noqa: E402
from openfdd_security.config import FixtureRefs, ProbeConfig  # noqa: E402
from openfdd_security.ssrf_policy import classify_url, forbidden_urls  # noqa: E402
from openfdd_security import SUITES  # noqa: E402
from openfdd_security.suites import SuiteContext, run_suite_ssrf  # noqa: E402
from openfdd_security.transport import Budget, SafeHttpClient  # noqa: E402


class BoundedMatrixSsrfTest(unittest.TestCase):
    def test_matrix_selftest(self) -> None:
        report = matrix_selftest()
        self.assertTrue(report["ok"], msg=json.dumps(report, indent=2))

    def test_ssrf_suite_registered(self) -> None:
        self.assertIn("ssrf", SUITES)

    def test_forbidden_metadata_urls(self) -> None:
        for url in forbidden_urls():
            result = classify_url(url)
            self.assertEqual(result["class"], "forbidden", msg=url)
            self.assertFalse(result["ok"], msg=url)

    def test_loopback_is_canary_class(self) -> None:
        result = classify_url("http://127.0.0.1:18081/hit")
        self.assertEqual(result["class"], "canary")

    def test_incomplete_canary_evidence_blocked(self) -> None:
        """Self-declared ok/status without correlated fields cannot qualify."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ev.json"
            path.write_text(json.dumps({"ok": True, "status": "PASS", "forbidden_hits": 0}))
            results: list = []
            cfg = ProbeConfig(raw={}, origin_allowlist=[], identities={}, fixtures=FixtureRefs())
            client = SafeHttpClient(
                "http://127.0.0.1:9",
                budget=Budget(max_requests=5, cleanup_reserved=0),
            )
            ctx = SuiteContext(client, cfg, "isolated_full", results.append)
            with mock.patch.dict(os.environ, {"OPENFDD_SSRF_CANARY_EVIDENCE_JSON": str(path)}):
                run_suite_ssrf(ctx)
            by_id = {c.check_id: c for c in results}
            self.assertEqual(by_id["ssrf.canary.forbidden_zero_hits"].status, "BLOCKED")
            self.assertEqual(by_id["ssrf.product_rust_path.bound"].status, "BLOCKED")


if __name__ == "__main__":
    unittest.main()
