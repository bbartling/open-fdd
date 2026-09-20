"""ZAP AF disposable runner: plan hygiene + selftest BLOCKED (no fake PASS).

Run: python3 -B -m unittest discover -s tests/qualification -v
"""
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
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


if __name__ == "__main__":
    unittest.main()
