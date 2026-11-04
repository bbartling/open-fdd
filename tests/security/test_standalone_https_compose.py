#!/usr/bin/env python3
"""UA-02: portal HTTPS overlay must not publish plaintext web:3000."""
from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class StandaloneHttpsComposeTest(unittest.TestCase):
    def test_merged_config_hides_web_and_has_no_broker(self) -> None:
        env = os.environ.copy()
        env["OPENFDD_JWT_SECRET"] = "test-jwt-secret-for-compose-config"
        env["OPENFDD_ADMIN_PASSWORD"] = "test-admin"
        env["OPENFDD_CENTRAL_BIND"] = "127.0.0.1"
        cmd = [
            "docker",
            "compose",
            "-f",
            "docker/compose.portal.yml",
            "-f",
            "docker/compose.standalone.https.yml",
            "config",
        ]
        try:
            out = subprocess.check_output(cmd, cwd=ROOT, env=env, text=True, stderr=subprocess.STDOUT)
        except FileNotFoundError:
            self.skipTest("docker not available")
        except subprocess.CalledProcessError as exc:
            self.fail(f"compose config failed: {exc.output[-500:]}")

        import yaml

        cfg = yaml.safe_load(out)
        services = cfg.get("services") or {}
        self.assertNotIn("web", services, "default portal recipe must not include openfdd-web")
        self.assertNotIn("mqtt", services)
        central_ports = services["central"].get("ports") or []
        self.assertEqual(central_ports, [], f"central must not publish LAN ports, got {central_ports}")
        caddy_ports = services["caddy"].get("ports") or []
        published = {str(p.get("published")) for p in caddy_ports}
        self.assertTrue({"80", "443"}.issubset(published), caddy_ports)


if __name__ == "__main__":
    unittest.main()
