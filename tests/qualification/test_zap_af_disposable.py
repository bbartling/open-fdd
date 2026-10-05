"""ZAP AF disposable runner: plan hygiene + selftest BLOCKED (no fake PASS).

Run: python3 -B -m unittest discover -s tests/qualification -v
"""
from __future__ import annotations

import importlib.util
import contextlib
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "scripts/qualification/zap/af_plan.yaml"
MODULE_PATH = ROOT / "scripts/qualification/zap/run_af_disposable.py"

SPEC = importlib.util.spec_from_file_location("run_af_disposable", MODULE_PATH)
af = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(af)


class ZapAfPlanHygieneTest(unittest.TestCase):
    def test_af_plan_has_no_hardcoded_bearer_or_jwt(self):
        raw = PLAN.read_text(encoding="utf-8")
        self.assertNotRegex(raw, r"Bearer\s+(?!\$\{)[A-Za-z0-9\-_\.=]+")
        self.assertNotRegex(raw, r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")
        self.assertIn("${ZAP_AUTH_HEADER_VALUE}", raw)
        self.assertIn("${ZAP_TARGET_ORIGIN}", raw)

    def test_validate_af_plan_accepts_repo_plan(self):
        errs = af.validate_af_plan(PLAN)
        self.assertEqual(errs, [], errs)

    def test_validate_af_plan_rejects_hardcoded_bearer(self):
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / "bad.yaml"
            bad.write_text(
                PLAN.read_text(encoding="utf-8").replace(
                    "${ZAP_AUTH_HEADER_VALUE}",
                    "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.aaaa.bbbb",
                ),
                encoding="utf-8",
            )
            errs = af.validate_af_plan(bad)
            self.assertTrue(any("Bearer" in e or "JWT" in e for e in errs), errs)


class ZapAfAuthMeSchemaTest(unittest.TestCase):
    def test_requires_role_and_subject(self):
        ok = af.verify_auth_me_response(
            status=200,
            body=b'{"role":"admin","sub":"admin"}',
            content_type="application/json",
        )
        self.assertTrue(ok["ok"])
        self.assertTrue(ok["schema_ok"])

    def test_rejects_200_without_identity(self):
        bad = af.verify_auth_me_response(
            status=200,
            body=b'{"ok":true}',
            content_type="application/json",
        )
        self.assertFalse(bad["ok"])
        self.assertEqual(bad.get("error"), "missing_role_or_subject")

    def test_rejects_html_200(self):
        bad = af.verify_auth_me_response(
            status=200,
            body=b"<html>login</html>",
            content_type="text/html",
        )
        self.assertFalse(bad["ok"])

    def test_report_string_auth_me_is_not_proof(self):
        summary = af.summarize_zap_json(
            {
                "site": [
                    {
                        "@name": "http://fixture.invalid",
                        "alerts": [
                            {
                                "riskcode": "0",
                                "name": "info",
                                "url": "http://fixture.invalid/api/auth/me",
                            }
                        ],
                    }
                ]
            }
        )
        self.assertTrue(summary["auth_me_url_mention"])
        self.assertFalse(summary["auth_me_hit"])
        # Still not a substitute for verify_auth_me_response.
        self.assertFalse(
            af.verify_auth_me_response(status=401, body=b"{}", content_type="application/json")[
                "ok"
            ]
        )

    def test_structured_auth_traffic_is_required_for_hit(self):
        summary = af.summarize_zap_json(
            {
                "site": [{"@name": "http://fixture.invalid", "alerts": []}],
                "openfdd_auth_traffic": {
                    "method": "GET",
                    "path": "/api/auth/me",
                    "status": 200,
                    "identity_schema_ok": True,
                    "origin": "scanner",
                },
            }
        )
        self.assertTrue(summary["auth_me_hit"])
        self.assertFalse(summary["auth_me_url_mention"])


class ZapAfSelftestTest(unittest.TestCase):
    def test_selftest_exits_blocked_not_pass(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "zap_af_verdict.json"
            rc = af.main(["--selftest", "--out", str(out)])
            self.assertEqual(rc, 2, "selftest must be BLOCKED (exit 2), never PASS")
            verdict = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(verdict["status"], "BLOCKED")
            self.assertTrue(verdict["plan_hygiene_ok"])
            self.assertEqual(verdict["suite"], "zap_af_authenticated_v1")
            blob = json.dumps(verdict)
            self.assertNotRegex(blob, r"eyJ[A-Za-z0-9_\-]{10,}\.")
            self.assertNotIn("Bearer eyJ", blob)

    def test_execute_without_env_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "v.json"
            env = {
                k: v
                for k, v in os.environ.items()
                if k
                not in (
                    "OPENFDD_ZAP_AF_EXECUTE",
                    "ZAP_TARGET_ORIGIN",
                    "ZAP_AUTH_HEADER_VALUE",
                )
            }
            with mock.patch.dict(os.environ, env, clear=True):
                rc = af.main(["--out", str(out)])
            self.assertEqual(rc, 2)
            verdict = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(verdict["status"], "BLOCKED")
            self.assertFalse(verdict.get("execute_requested"))


class ZapAfExecuteVerdictTest(unittest.TestCase):
    def run_synthetic(self, report, *, scanner_rc=0, target="http://fixture.invalid", stale=False):
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            (work / "openapi.json").write_text(
                json.dumps(
                    {
                        "openapi": "3.0.3",
                        "info": {"title": "fixture", "version": "0"},
                        "paths": {"/api/health": {"get": {"responses": {"200": {"description": "ok"}}}}},
                    }
                ),
                encoding="utf-8",
            )
            report_path = work / "zap-af-report.json"
            report_path.write_text(json.dumps(report), encoding="utf-8")
            if stale:
                os.utime(report_path, (1, 1))
            else:
                future = time.time() + 5
                os.utime(report_path, (future, future))
            out = work / "verdict.json"
            env = {
                "ZAP_TARGET_ORIGIN": target,
                "ZAP_AUTH_HEADER_VALUE": "Bearer synthetic",
                "ZAP_AF_WORK_DIR": str(work),
            }
            auth_ok = {
                "ok": True,
                "status": 200,
                "path": "/api/auth/me",
                "schema_ok": True,
                "role_present": True,
                "subject_present": True,
            }

            class _Resp:
                status = 200
                headers = {"Content-Type": "application/json"}

                def getcode(self):
                    return 200

                def read(self, *_a, **_k):
                    return b'{"role":"admin","sub":"admin"}'

                def __enter__(self):
                    return self

                def __exit__(self, *_a):
                    return False

            with (
                mock.patch.dict(os.environ, env, clear=True),
                mock.patch.object(af, "detect_zap", return_value=("zap.sh", "synthetic-zap")),
                mock.patch.object(af, "_run_zap_sh", return_value=scanner_rc),
                mock.patch.object(af, "verify_auth_me_response", return_value=auth_ok),
                mock.patch("urllib.request.urlopen", return_value=_Resp()),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                rc = af.run_execute(out)
            return rc, json.loads(out.read_text(encoding="utf-8"))

    def test_scanner_error_cannot_pass_with_existing_report(self):
        rc, verdict = self.run_synthetic(
            {"site": [{"@name": "http://fixture.invalid", "alerts": []}]},
            scanner_rc=1,
        )
        self.assertNotEqual(rc, 0)
        self.assertEqual(verdict["status"], "FAIL")

    def test_empty_site_object_is_rejected(self):
        rc, verdict = self.run_synthetic({"site": [{}]})
        self.assertNotEqual(rc, 0)
        self.assertNotEqual(verdict["status"], "PASS")

    def test_undispositioned_medium_fails(self):
        rc, verdict = self.run_synthetic(
            {
                "site": [
                    {
                        "@name": "http://fixture.invalid",
                        "alerts": [
                            {
                                "riskcode": "2",
                                "alert": "synthetic-medium",
                                "pluginid": "99999",
                            }
                        ],
                    }
                ]
            }
        )
        self.assertNotEqual(rc, 0)
        self.assertEqual(verdict["status"], "FAIL")
        self.assertIn("undispositioned", verdict.get("notes", ""))

    def test_typed_medium_disposition_allows_pass(self):
        covered, errs = af.disposition_medium_alerts(
            medium_plugin_ids=["10055", "90003"],
            medium_alert_names=[
                "CSP: style-src unsafe-inline",
                "Sub Resource Integrity Attribute Missing",
            ],
            dispositions=af.load_medium_dispositions(),
            today="2026-10-03",
        )
        self.assertEqual(errs, [])
        self.assertEqual(sorted(covered), ["10055", "90003"])

    def test_stale_or_wrong_target_report_is_rejected(self):
        cases = (
            (
                {"site": [{"@name": "http://fixture.invalid", "alerts": []}]},
                "http://fixture.invalid",
                True,
            ),
            (
                {"site": [{"@name": "http://previous.invalid", "alerts": []}]},
                "http://fixture.invalid",
                False,
            ),
        )
        for report, target, stale in cases:
            with self.subTest(stale=stale):
                rc, verdict = self.run_synthetic(report, target=target, stale=stale)
                self.assertNotEqual(rc, 0)
                self.assertNotEqual(verdict["status"], "PASS")

    def test_clean_report_passes_with_verified_auth(self):
        # Passive mode: preflight schema is enough; URL mention is not scanner proof.
        rc, verdict = self.run_synthetic(
            {
                "site": [
                    {
                        "@name": "http://fixture.invalid",
                        "urls": ["http://fixture.invalid/api/auth/me"],
                        "alerts": [],
                    }
                ]
            }
        )
        self.assertEqual(rc, 0)
        self.assertEqual(verdict["status"], "PASS")
        self.assertTrue(verdict.get("auth_me_hit"))
        self.assertFalse(verdict.get("auth_me_in_zap_report"))
        self.assertTrue(verdict.get("auth_me_url_mention"))
        self.assertEqual(verdict.get("auth_proof"), "preflight_status_identity_schema")

    def test_active_url_mention_alone_cannot_pass(self):
        """Q-03: URL text ending in /api/auth/me is not scanner auth traffic."""
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            (work / "openapi.json").write_text(
                json.dumps(
                    {
                        "openapi": "3.0.3",
                        "info": {"title": "fixture", "version": "0"},
                        "paths": {},
                    }
                ),
                encoding="utf-8",
            )
            report_path = work / "zap-af-report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "site": [
                            {
                                "@name": "http://fixture.invalid",
                                "urls": ["http://fixture.invalid/api/auth/me"],
                                "alerts": [],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            future = time.time() + 5
            os.utime(report_path, (future, future))
            out = work / "verdict.json"
            env = {
                "ZAP_TARGET_ORIGIN": "http://fixture.invalid",
                "ZAP_AUTH_HEADER_VALUE": "Bearer synthetic",
                "ZAP_AF_WORK_DIR": str(work),
                "OPENFDD_ZAP_AF_ACTIVE": "1",
            }
            auth_ok = {
                "ok": True,
                "status": 200,
                "path": "/api/auth/me",
                "schema_ok": True,
                "role_present": True,
                "subject_present": True,
            }

            class _Resp:
                status = 200
                headers = {"Content-Type": "application/json"}

                def getcode(self):
                    return 200

                def read(self, *_a, **_k):
                    return b'{"role":"admin","sub":"admin"}'

                def __enter__(self):
                    return self

                def __exit__(self, *_a):
                    return False

            with (
                mock.patch.dict(os.environ, env, clear=True),
                mock.patch.object(af, "detect_zap", return_value=("zap.sh", "synthetic-zap")),
                mock.patch.object(af, "_run_zap_sh", return_value=0),
                mock.patch.object(af, "verify_auth_me_response", return_value=auth_ok),
                mock.patch("urllib.request.urlopen", return_value=_Resp()),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                rc = af.run_execute(out)
            verdict = json.loads(out.read_text(encoding="utf-8"))
            self.assertNotEqual(rc, 0)
            self.assertEqual(verdict["status"], "FAIL")
            self.assertIn("structured", verdict.get("notes", ""))

    def test_active_structured_scanner_traffic_passes(self):
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            (work / "openapi.json").write_text(
                json.dumps(
                    {
                        "openapi": "3.0.3",
                        "info": {"title": "fixture", "version": "0"},
                        "paths": {"/api/health": {"get": {"responses": {"200": {"description": "ok"}}}}},
                    }
                ),
                encoding="utf-8",
            )
            report_path = work / "zap-af-report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "site": [{"@name": "http://fixture.invalid", "alerts": []}],
                        "openfdd_auth_traffic": {
                            "method": "GET",
                            "path": "/api/auth/me",
                            "status": 200,
                            "identity_schema_ok": True,
                            "origin": "scanner",
                        },
                    }
                ),
                encoding="utf-8",
            )
            future = time.time() + 5
            os.utime(report_path, (future, future))
            out = work / "verdict.json"
            env = {
                "ZAP_TARGET_ORIGIN": "http://fixture.invalid",
                "ZAP_AUTH_HEADER_VALUE": "Bearer synthetic",
                "ZAP_AF_WORK_DIR": str(work),
                "OPENFDD_ZAP_AF_ACTIVE": "1",
            }
            auth_ok = {
                "ok": True,
                "status": 200,
                "path": "/api/auth/me",
                "schema_ok": True,
                "role_present": True,
                "subject_present": True,
            }

            class _Resp:
                status = 200
                headers = {"Content-Type": "application/json"}

                def getcode(self):
                    return 200

                def read(self, *_a, **_k):
                    return b'{"role":"admin","sub":"admin"}'

                def __enter__(self):
                    return self

                def __exit__(self, *_a):
                    return False

            with (
                mock.patch.dict(os.environ, env, clear=True),
                mock.patch.object(af, "detect_zap", return_value=("zap.sh", "synthetic-zap")),
                mock.patch.object(af, "_run_zap_sh", return_value=0),
                mock.patch.object(af, "verify_auth_me_response", return_value=auth_ok),
                mock.patch("urllib.request.urlopen", return_value=_Resp()),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                rc = af.run_execute(out)
            verdict = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(rc, 0)
            self.assertEqual(verdict["status"], "PASS")
            self.assertTrue(verdict.get("auth_me_in_zap_report"))
            self.assertEqual(verdict.get("auth_proof"), "preflight_schema+scanner_auth_traffic")

    def test_active_without_scanner_auth_me_fails(self):
        """Active AF cannot PASS on preflight alone (A06)."""
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            (work / "openapi.json").write_text(
                json.dumps(
                    {
                        "openapi": "3.0.3",
                        "info": {"title": "fixture", "version": "0"},
                        "paths": {},
                    }
                ),
                encoding="utf-8",
            )
            report_path = work / "zap-af-report.json"
            report_path.write_text(
                json.dumps(
                    {"site": [{"@name": "http://fixture.invalid", "alerts": []}]}
                ),
                encoding="utf-8",
            )
            future = time.time() + 5
            os.utime(report_path, (future, future))
            out = work / "verdict.json"
            env = {
                "ZAP_TARGET_ORIGIN": "http://fixture.invalid",
                "ZAP_AUTH_HEADER_VALUE": "Bearer synthetic",
                "ZAP_AF_WORK_DIR": str(work),
                "OPENFDD_ZAP_AF_ACTIVE": "1",
            }
            auth_ok = {
                "ok": True,
                "status": 200,
                "path": "/api/auth/me",
                "schema_ok": True,
                "role_present": True,
                "subject_present": True,
            }

            class _Resp:
                status = 200
                headers = {"Content-Type": "application/json"}

                def getcode(self):
                    return 200

                def read(self, *_a, **_k):
                    return b'{"role":"admin","sub":"admin"}'

                def __enter__(self):
                    return self

                def __exit__(self, *_a):
                    return False

            with (
                mock.patch.dict(os.environ, env, clear=True),
                mock.patch.object(af, "detect_zap", return_value=("zap.sh", "synthetic-zap")),
                mock.patch.object(af, "_run_zap_sh", return_value=0),
                mock.patch.object(af, "verify_auth_me_response", return_value=auth_ok),
                mock.patch("urllib.request.urlopen", return_value=_Resp()),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                rc = af.run_execute(out)
            verdict = json.loads(out.read_text(encoding="utf-8"))
            self.assertNotEqual(rc, 0)
            self.assertEqual(verdict["status"], "FAIL")
            self.assertIn("scanner-origin", verdict.get("notes", ""))


class ZapDigestPinTest(unittest.TestCase):
    def test_default_image_is_digest_pinned(self):
        self.assertTrue(af.zap_image_is_digest_pinned(af.DEFAULT_ZAP_IMAGE))

    def test_moving_tag_rejected_when_required(self):
        self.assertFalse(af.zap_image_is_digest_pinned("ghcr.io/zaproxy/zaproxy:stable"))


if __name__ == "__main__":
    unittest.main()
