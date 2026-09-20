"""Regression tests for exact /api/auth/me tenant membership validation."""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "security"))

from openfdd_security.config import FixtureRefs, IdentityRef, ProbeConfig  # noqa: E402
from openfdd_security.suites import SuiteContext, _login_me  # noqa: E402
from openfdd_security.transport import Response  # noqa: E402


class SyntheticIdentityClient:
    def __init__(self, me_body):
        self.me_body = me_body

    def request(self, method, path, **kwargs):
        body = {"token": "synthetic-token"} if path == "/api/auth/login" else self.me_body
        return Response(
            200,
            {"Content-Type": "application/json"},
            json.dumps(body).encode(),
            0,
            "http://fixture.invalid",
        )


class IdentityTenantMembershipTest(unittest.TestCase):
    def run_login(self, tenant_ids):
        results = []
        ident = IdentityRef(
            alias="operator_a",
            password_env="AUDIT_SYNTHETIC_PASSWORD",
            role="operator",
            tenant_ids=["synthetic-a"],
        )
        cfg = ProbeConfig(
            raw={},
            origin_allowlist=[],
            identities={"operator_a": ident},
            fixtures=FixtureRefs(),
        )
        ctx = SuiteContext(
            SyntheticIdentityClient(
                {"sub": "synthetic-a", "role": "operator", **tenant_ids}
            ),
            cfg,
            "live_readonly",
            results.append,
        )
        with patch.dict(
            os.environ, {"AUDIT_SYNTHETIC_PASSWORD": "synthetic-only"}, clear=True
        ):
            _login_me(
                ctx,
                "operator_a",
                "synthetic.identity",
                default_user="synthetic-a",
            )
        return results[-1]

    def test_actual_tenant_ids_must_match_expected_exactly(self):
        for actual in (["synthetic-b"], ["synthetic-a", "synthetic-extra"]):
            with self.subTest(actual=actual):
                result = self.run_login({"tenant_ids": actual})
                self.assertEqual(result.status, "FAIL")

    def test_missing_membership_cannot_pass(self):
        result = self.run_login({})
        self.assertEqual(result.status, "FAIL")


if __name__ == "__main__":
    unittest.main()
