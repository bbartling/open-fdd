"""Astra C-PY: bounded matrix + SSRF policy offline tests."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "security"))

from bounded_matrix import selftest as matrix_selftest  # noqa: E402
from openfdd_security.ssrf_policy import classify_url, forbidden_urls  # noqa: E402
from openfdd_security import SUITES  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
