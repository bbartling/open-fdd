"""MQTT tenant ACL fixture semantics + generator honesty."""
from __future__ import annotations

import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "scripts" / "security" / "fixtures" / "mqtt_tenant_acl"
sys.path.insert(0, str(FIX))
sys.path.insert(0, str(ROOT / "scripts" / "security"))

from generate_acl import (  # noqa: E402
    edge_topic_prefix,
    load_tenants,
    render_acl,
    semantic_errors,
    write_acl,
)
import mqtt_tenant_acl_observer as observer  # noqa: E402


class MqttTenantAclFixtureTest(unittest.TestCase):
    def test_committed_acl_matches_generator(self):
        committed = (FIX / "acl").read_text(encoding="utf-8")
        self.assertEqual(committed, render_acl())

    def test_two_tenants_own_and_foreign(self):
        cfg = load_tenants()
        self.assertGreaterEqual(len(cfg["tenants"]), 2)
        text = render_acl(cfg)
        errs = semantic_errors(text, cfg)
        self.assertEqual(errs, [], msg="\n".join(errs))
        a, b = cfg["tenants"][0], cfg["tenants"][1]
        pref_a = edge_topic_prefix(a["tenant_id"], a["building_id"], a["edge_id"])
        pref_b = edge_topic_prefix(b["tenant_id"], b["building_id"], b["edge_id"])
        self.assertIn(f"user {a['edge_user']}", text)
        self.assertIn(f"topic write {pref_a}/#", text)
        self.assertIn(f"user {b['edge_user']}", text)
        self.assertIn(f"topic write {pref_b}/#", text)
        # Edge A must not receive an explicit grant under tenant B.
        a_block = text.split(f"user {a['edge_user']}")[1].split("user ")[0]
        self.assertNotIn(f"/tenants/{b['tenant_id']}/", a_block)

    def test_rejects_cross_tenant_wildcard(self):
        bad = (
            "user edge:tenant_a:bldg_a:fieldbus-1\n"
            "topic write openfdd/v1/tenants/+/buildings/+/edges/+/telemetry/#\n"
        )
        errs = semantic_errors(bad)
        self.assertTrue(any("wildcard" in e or "foreign" in e for e in errs))

    def test_write_acl_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "acl"
            write_acl(out)
            self.assertEqual(semantic_errors(out.read_text(encoding="utf-8")), [])

    def test_entrypoint_key_mode_640(self):
        ep = ROOT / "services" / "mqtt" / "docker-entrypoint-openfdd.sh"
        text = ep.read_text(encoding="utf-8")
        self.assertIn("chmod 640", text)
        self.assertIn("server.key.pem", text)

    def test_skipped_live_is_not_ok_by_default(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(
            observer, "docker_available", return_value=False
        ):
            verdict = observer.observe(
                out_dir=Path(td), require_live=False, skip_live=False
            )
        self.assertFalse(verdict["ok"])
        self.assertNotEqual(verdict["status"], "PASS")

    def test_require_live_plus_skip_live_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            verdict = observer.observe(
                out_dir=Path(td), require_live=True, skip_live=True
            )
        self.assertFalse(verdict["ok"])
        self.assertNotEqual(verdict["status"], "PASS")

    def test_live_blocked_is_never_ok(self):
        blocked = {
            "check": "mqtt.acl.live_broker_observer",
            "status": "BLOCKED",
            "detail": "synthetic dependency unavailable",
        }
        with (
            tempfile.TemporaryDirectory() as td,
            mock.patch.object(observer, "docker_available", return_value=True),
            mock.patch.object(observer, "run_live_broker", return_value=blocked),
        ):
            verdict = observer.observe(
                out_dir=Path(td), require_live=False, skip_live=False
            )
        self.assertFalse(verdict["ok"])
        self.assertNotEqual(verdict["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
