"""Phase 3 — explicit clock for JWT expiry boundary tokens."""
from __future__ import annotations

import base64
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/security"))

from openfdd_security.jwtutil import (  # noqa: E402
    make_expired_token,
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


if __name__ == "__main__":
    unittest.main()
