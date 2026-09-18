"""Broken local HTTP fixtures must trip named detectors; healthy must not."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/security"))
sys.path.insert(0, str(ROOT / "scripts/security/fixtures"))

from broken_http import SECRET, FixtureServer  # noqa: E402
from openfdd_security.runner import run_probe  # noqa: E402

EXAMPLE = ROOT / "scripts/security/config/example_security_fixtures.json"


def _cfg_for_port(port: int, path: Path) -> Path:
    data = json.loads(EXAMPLE.read_text())
    origin = f"http://127.0.0.1:{port}"
    data["origin_allowlist"] = [origin]
    path.write_text(json.dumps(data))
    return path


def _run(mode: str, td: str) -> dict:
    srv = FixtureServer(mode=mode)
    base = srv.start()
    port = srv.port
    try:
        cfg = _cfg_for_port(port, Path(td) / "cfg.json")
        out = Path(td) / "out"
        env = {
            "OPENFDD_ADMIN_USER": "admin",
            "OPENFDD_ADMIN_PASSWORD": "admin-pass",
            "OPENFDD_USER_A_OPS_USER": "ops_a",
            "OPENFDD_USER_A_OPS_PASSWORD": "ops-a-pass",
            "OPENFDD_USER_B_OPS_USER": "ops_b",
            "OPENFDD_USER_B_OPS_PASSWORD": "ops-b-pass",
            "OPENFDD_VIEWER_USER": "viewer",
            "OPENFDD_VIEWER_PASSWORD": "viewer-pass",
        }
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            report, _ = run_probe(
                config_path=cfg,
                base_url=base,
                profile="isolated_full",
                suites=None,
                execute=True,
                dry_run=False,
                max_requests=80,
                timeout=5.0,
                deadline=60.0,
                rate=20.0,
                output_dir=out,
                allow_fixture_writes=True,
                isolated_jwt_secret=SECRET,
            )
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        return {c.check_id: c for c in report.checks}
    finally:
        srv.stop()


class BrokenFixtureDetectorsTest(unittest.TestCase):
    def test_healthy_core_detectors_pass(self):
        with tempfile.TemporaryDirectory() as td:
            checks = _run("healthy", td)
            self.assertEqual(checks["x.preauth.health_public"].status, "PASS")
            self.assertEqual(
                checks["y.detector.always_401_invalidates_authz"].status, "PASS"
            )
            self.assertEqual(checks["y.detector.empty_200_not_deny"].status, "PASS")
            self.assertEqual(checks["y.detector.html_200_not_deny"].status, "PASS")
            self.assertEqual(checks["y.detector.foreign_canary_leak"].status, "PASS")
            self.assertEqual(
                checks["z.detector.redirect_no_credential_forward"].status, "PASS"
            )

    def test_always_401_detector(self):
        with tempfile.TemporaryDirectory() as td:
            checks = _run("always_401", td)
            self.assertEqual(
                checks["y.detector.always_401_invalidates_authz"].status,
                "FAIL",
                "always_401 fixture must fail always_401 detector",
            )

    def test_empty_200_detector(self):
        with tempfile.TemporaryDirectory() as td:
            checks = _run("empty_200", td)
            self.assertEqual(checks["y.detector.empty_200_not_deny"].status, "FAIL")

    def test_html_200_detector(self):
        with tempfile.TemporaryDirectory() as td:
            checks = _run("html_200", td)
            self.assertEqual(checks["y.detector.html_200_not_deny"].status, "FAIL")

    def test_foreign_canary_detector(self):
        with tempfile.TemporaryDirectory() as td:
            checks = _run("foreign_canary", td)
            self.assertEqual(checks["y.detector.foreign_canary_leak"].status, "FAIL")

    def test_jwt_alg_none_rejected_on_healthy(self):
        with tempfile.TemporaryDirectory() as td:
            checks = _run("healthy", td)
            self.assertEqual(checks["x.jwt.alg_none_rejected"].status, "PASS")

    def test_jwt_sig_bypass_fails_tamper_or_sibling(self):
        with tempfile.TemporaryDirectory() as td:
            checks = _run("jwt_bypass_sig", td)
            # Tampered token accepted → FAIL on tampered_sig_rejected
            self.assertEqual(
                checks["x.jwt.tampered_sig_rejected"].status,
                "FAIL",
                "sig bypass must fail tampered_sig detector",
            )

    def test_jwt_exp_bypass_fails_expired(self):
        with tempfile.TemporaryDirectory() as td:
            checks = _run("jwt_bypass_exp", td)
            self.assertEqual(checks["x.jwt.expired_signed_rejected"].status, "FAIL")

    def test_viewer_mutation_allowed_fails(self):
        with tempfile.TemporaryDirectory() as td:
            checks = _run("viewer_mutation", td)
            self.assertEqual(
                checks["y.authz.viewer_mutation_denied"].status, "FAIL"
            )

    def test_cors_evil_reflected(self):
        with tempfile.TemporaryDirectory() as td:
            checks = _run("cors_evil", td)
            self.assertEqual(
                checks["z.deploy.cors_disallow_evil"].status,
                "FAIL",
                "reflected ACAO must fail CORS detector",
            )

    def test_wrong_identity_fails_login_me(self):
        with tempfile.TemporaryDirectory() as td:
            checks = _run("wrong_identity", td)
            self.assertEqual(checks["x.auth.admin_login_me"].status, "FAIL")

    def test_oversized_body_cap(self):
        with tempfile.TemporaryDirectory() as td:
            checks = _run("oversized", td)
            self.assertEqual(
                checks["z.abuse.oversized_body_blocked"].status, "PASS"
            )


if __name__ == "__main__":
    unittest.main()
