"""Standalone HTTPS bootstrap: compose/Caddyfile/exposure lint (CI, no Docker)."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "security"))

from peer_probe_https import (  # noqa: E402
    CADDYFILE,
    COMPOSE,
    EXPOSURE,
    lint_caddyfile,
    lint_compose,
    lint_exposure,
    run_config_lint,
)


class StandaloneHttpsBootstrapTest(unittest.TestCase):
    def test_assets_exist(self):
        self.assertTrue(COMPOSE.is_file(), COMPOSE)
        self.assertTrue(CADDYFILE.is_file(), CADDYFILE)
        self.assertTrue(EXPOSURE.is_file(), EXPOSURE)

    def test_compose_lint(self):
        errs = lint_compose(COMPOSE.read_text(encoding="utf-8"))
        self.assertEqual(errs, [], msg="\n".join(errs))

    def test_caddyfile_lint(self):
        errs = lint_caddyfile(CADDYFILE.read_text(encoding="utf-8"))
        self.assertEqual(errs, [], msg="\n".join(errs))

    def test_exposure_manifest(self):
        data = json.loads(EXPOSURE.read_text(encoding="utf-8"))
        errs = lint_exposure(data)
        self.assertEqual(errs, [], msg="\n".join(errs))

    def test_config_lint_report_ok(self):
        report = run_config_lint()
        self.assertTrue(report["ok"], msg=json.dumps(report, indent=2))
        self.assertEqual(report["verdict"], "PASS")

    def test_compose_rejects_plaintext_central_publish(self):
        bad = COMPOSE.read_text(encoding="utf-8") + "\n  central:\n    ports:\n      - \"8080:8080\"\n"
        errs = lint_compose(bad)
        self.assertTrue(any("8080" in e for e in errs))

    def test_caddyfile_rejects_http_reverse_proxy(self):
        bad = (
            "http://localhost {\n"
            "\treverse_proxy web:8080\n"
            "}\n"
        )
        errs = lint_caddyfile(bad)
        self.assertTrue(errs, msg="expected plaintext reverse_proxy to fail")


if __name__ == "__main__":
    unittest.main()
