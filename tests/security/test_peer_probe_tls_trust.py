#!/usr/bin/env python3
"""UA-02: HTTPS probe must require trusted SSL context (no silent verify=False)."""
from __future__ import annotations

import ssl
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
import sys

sys.path.insert(0, str(ROOT / "scripts" / "security"))

from peer_probe_https import (  # noqa: E402
    _http_probe,
    _openssl_self_signed,
    _ssl_trust_ca,
)


class PeerProbeTlsTrustTest(unittest.TestCase):
    def test_https_probe_requires_explicit_context(self) -> None:
        with self.assertRaises(ValueError):
            _http_probe("https://localhost:1/api/health")

    def test_trust_ca_loads_probe_pem(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cert_dir = Path(td)
            _openssl_self_signed(cert_dir)
            ctx = _ssl_trust_ca(cert_dir / "server.crt")
            self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
            self.assertTrue(ctx.check_hostname)


if __name__ == "__main__":
    unittest.main()
