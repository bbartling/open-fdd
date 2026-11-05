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
    assert_product_images,
    resolve_candidate_images,
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

    def test_candidate_rejects_stub_web(self) -> None:
        errs = assert_product_images(
            {
                "central": "ghcr.io/bbartling/openfdd-central:sha-abc1234",
                "web": "python:3.12-alpine",
                "mqtt": "ghcr.io/bbartling/openfdd-mqtt:sha-abc1234",
                "caddy": "caddy:2.8-alpine",
            }
        )
        self.assertTrue(errs)
        self.assertTrue(any("web" in e for e in errs))

    def test_candidate_accepts_product_refs(self) -> None:
        images = resolve_candidate_images("sha-af4086f")
        self.assertEqual(assert_product_images(images), [])

    def test_candidate_requires_tag(self) -> None:
        with self.assertRaises(ValueError):
            resolve_candidate_images("")


if __name__ == "__main__":
    unittest.main()
