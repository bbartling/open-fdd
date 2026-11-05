"""Host/runtime readiness selftest (UA-08 / Astra A10)."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "security"))

from host_runtime_probe import (  # noqa: E402
    PROFILES,
    bind_policy_ok,
    classify_bind,
    parse_ssh_permit_root_values,
    run,
)


class HostRuntimeProbeTest(unittest.TestCase):
    def test_selftest_pass(self):
        report = run("selftest", "field_only_ot")
        self.assertTrue(report["ok"], msg=json.dumps(report, indent=2))
        self.assertEqual(report["verdict"], "PASS")
        self.assertEqual(report["schema_version"], "openfdd_host_runtime_probe_v2")

    def test_profiles_cover_deployment_contract(self):
        for name in (
            "standalone_https",
            "field_only_ot",
            "cloud_mqtt_hub",
            "ot_local_bacnet_modbus",
            "ot_local_haystack",
            "local_development",
        ):
            self.assertIn(name, PROFILES)

    def test_field_only_forbids_local_broker_ports(self):
        ports = {p["port"] for p in PROFILES["field_only_ot"]["forbidden_listen"]}
        self.assertTrue({8080, 3000, 8883}.issubset(ports))

    def test_haystack_forbids_bacnet_udp(self):
        items = PROFILES["ot_local_haystack"]["forbidden_listen"]
        self.assertTrue(
            any(p.get("proto") == "udp" and p.get("port") == 47808 for p in items)
        )

    def test_bind_policy_distinguishes_loopback_and_wildcard(self):
        self.assertEqual(classify_bind("127.0.0.1"), "loopback")
        self.assertEqual(classify_bind("0.0.0.0"), "wildcard")
        ok, _ = bind_policy_ok("loopback_only", ["127.0.0.1"])
        self.assertTrue(ok)
        ok, _ = bind_policy_ok("loopback_only", ["0.0.0.0"])
        self.assertFalse(ok)
        ok, _ = bind_policy_ok("must_absent", ["0.0.0.0"])
        self.assertFalse(ok)

    def test_ssh_include_is_parsed(self):
        text = "Include /tmp/dropin.conf\nPermitRootLogin yes\n"
        vals = parse_ssh_permit_root_values(
            text, reader=lambda _p: "PermitRootLogin no\n"
        )
        self.assertIn("yes", vals)
        self.assertIn("no", vals)


if __name__ == "__main__":
    unittest.main()
