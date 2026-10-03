"""Phase 3 — explicit clock + denial token shapes for JWT helpers.

Product acceptance of these shapes is covered by `openfdd-central` `auth::tests`
(`verify_bearer` with an ephemeral harness key). Python helpers only mint bytes.
"""
from __future__ import annotations

import base64
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/security"))

from openfdd_security.jwtutil import (  # noqa: E402
    make_alg_none_token,
    make_expired_token,
    make_tampered_token,
    make_valid_token,
)


def _payload(token: str) -> dict:
    part = token.split(".")[1]
    pad = "=" * (-len(part) % 4)
    return json.loads(base64.urlsafe_b64decode(part + pad))


class JwtClockTests(unittest.TestCase):
    def test_valid_and_expired_respect_injected_clock(self):
        secret = b"harness-isolated-test-key-32b!!"
        now = 1_700_000_000
        valid = make_valid_token(secret, now_s=now, ttl_s=60)
        expired = make_expired_token(secret, now_s=now)
        self.assertEqual(_payload(valid)["iat"], now)
        self.assertEqual(_payload(valid)["exp"], now + 60)
        self.assertEqual(_payload(expired)["exp"], now - 120)
        self.assertLess(_payload(expired)["exp"], now)

    def test_alg_none_and_tampered_change_wire_bytes(self):
        secret = b"harness-isolated-test-key-32b!!"
        now = 1_700_000_000
        none_tok = make_alg_none_token(now_s=now)
        tampered = make_tampered_token(secret)
        self.assertTrue(none_tok.endswith("."))
        hdr = none_tok.split(".")[0]
        pad = "=" * (-len(hdr) % 4)
        self.assertEqual(json.loads(base64.urlsafe_b64decode(hdr + pad))["alg"], "none")
        # make_tampered_token flips the signature of a freshly minted admin token.
        parts = tampered.split(".")
        self.assertEqual(len(parts), 3)
        self.assertTrue(parts[2])
        self.assertEqual(_payload(tampered)["role"], "admin")


if __name__ == "__main__":
    unittest.main()
