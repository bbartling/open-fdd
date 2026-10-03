"""Astra A04 — nginx proxy trust / HSTS / per-route limits (static contract)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/qualification"))

from cache_retention_preview_health import check_nginx  # noqa: E402

NGINX = ROOT / "frontend" / "web" / "nginx.conf"


class NginxProxyContractTest(unittest.TestCase):
    def test_nginx_astra_a04_contract(self) -> None:
        text = NGINX.read_text(encoding="utf-8")
        errs = check_nginx(text)
        self.assertEqual(errs, [], msg="\n".join(errs))

    def test_hsts_map_uses_forwarded_https(self) -> None:
        text = NGINX.read_text(encoding="utf-8")
        self.assertIn("map $http_x_forwarded_proto $openfdd_hsts", text)
        self.assertIn('https "max-age=31536000; includeSubDomains"', text)

    def test_no_raw_scheme_forward_to_central(self) -> None:
        text = NGINX.read_text(encoding="utf-8")
        self.assertNotIn(
            "proxy_set_header X-Forwarded-Proto $scheme;",
            text,
        )


if __name__ == "__main__":
    unittest.main()
