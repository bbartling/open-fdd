"""Host/runtime readiness selftest (UA-08)."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "security"))

from host_runtime_probe import PROFILES, run  # noqa: E402


class HostRuntimeProbeTest(unittest.TestCase):
    def test_selftest_pass(self):
        report = run("selftest", "field_only_ot")
        self.assertTrue(report["ok"], msg=json.dumps(report, indent=2))
        self.assertEqual(report["verdict"], "PASS")

    def test_profiles_cover_both_ot_shapes(self):
        self.assertIn("standalone_https", PROFILES)
        self.assertIn("field_only_ot", PROFILES)

    def test_field_only_forbids_local_broker_ports(self):
        ports = {p["port"] for p in PROFILES["field_only_ot"]["forbidden_listen"]}
        self.assertTrue({8080, 3000, 8883}.issubset(ports))


if __name__ == "__main__":
    unittest.main()
