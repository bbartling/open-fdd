"""Astra A03 — Caddy TLS modes: provided / local_ca / lab (static lint)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "security"))

from peer_probe_https import lint_caddyfile, lint_compose  # noqa: E402

CADDY_DIR = ROOT / "deploy" / "caddy"
MODES = {
    "provided": CADDY_DIR / "Caddyfile.standalone.https",
    "local_ca": CADDY_DIR / "Caddyfile.standalone.https.local_ca",
    "lab": CADDY_DIR / "Caddyfile.standalone.https.lab",
}
COMPOSE = ROOT / "docker" / "compose.standalone.https.yml"


class CaddyTlsModesTest(unittest.TestCase):
    def test_all_mode_files_exist(self) -> None:
        for name, path in MODES.items():
            self.assertTrue(path.is_file(), msg=f"missing {name}: {path}")

    def test_each_mode_lints(self) -> None:
        for name, path in MODES.items():
            with self.subTest(mode=name):
                errs = lint_caddyfile(path.read_text(encoding="utf-8"))
                self.assertEqual(errs, [], msg=f"{name}: " + "\n".join(errs))

    def test_provided_uses_cert_files(self) -> None:
        text = MODES["provided"].read_text(encoding="utf-8")
        self.assertIn("tls /certs/server.crt /certs/server.key", text)

    def test_local_ca_uses_tls_internal(self) -> None:
        text = MODES["local_ca"].read_text(encoding="utf-8")
        self.assertIn("tls internal", text)

    def test_lab_uses_lab_certs(self) -> None:
        text = MODES["lab"].read_text(encoding="utf-8")
        self.assertIn("tls /certs/lab.crt /certs/lab.key", text)

    def test_compose_wires_public_host_and_mode(self) -> None:
        text = COMPOSE.read_text(encoding="utf-8")
        errs = lint_compose(text)
        self.assertEqual(errs, [], msg="\n".join(errs))
        self.assertIn("OPENFDD_PUBLIC_HOST", text)
        self.assertIn("OPENFDD_CADDY_TLS_MODE", text)
        self.assertIn("OPENFDD_CADDYFILE_SUFFIX", text)


if __name__ == "__main__":
    unittest.main()
