#!/usr/bin/env python3
"""UA-08/H0: BACnet MQTT CI must stage private keys 600/640 (RO broker mount)."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SMOKE = ROOT / "scripts" / "integration" / "bacnet_mqtt_container_smoke.sh"


class BacnetMqttCiKeyModesTest(unittest.TestCase):
    def test_smoke_does_not_world_chmod_all_pems(self) -> None:
        text = SMOKE.read_text(encoding="utf-8")
        self.assertFalse(
            re.search(r"chmod\s+644\s+.*\*\/\*\.pem", text),
            "blanket chmod 644 on *.pem breaks RO-mounted server.key under fail-closed mqtt",
        )
        self.assertIn("chmod 640", text)
        self.assertIn("server.key.pem", text)
        # Keys must be named explicitly at 640.
        self.assertRegex(
            text,
            r"chmod\s+640\s+\\\s*\n\s*\"\$TMP/mqtt/broker/server\.key\.pem\"",
        )


if __name__ == "__main__":
    unittest.main()
