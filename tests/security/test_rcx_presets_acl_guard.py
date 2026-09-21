"""UA-10: RCx presets list must enforce building ACL (permanent source guard)."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROUTES = ROOT / "services" / "central" / "src" / "routes.rs"


class RcxPresetsAclGuardTest(unittest.TestCase):
    def test_presets_list_denies_foreign_building(self):
        text = ROUTES.read_text(encoding="utf-8")
        m = re.search(
            r"async fn analytics_rcx_presets_list\((.*?)\)\s*->.*?\{(.*?)\n\}",
            text,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(m, "analytics_rcx_presets_list not found")
        body = m.group(2)
        self.assertIn(
            "deny_if_building_out_of_scope",
            body,
            "GET /api/analytics/rcx/presets must gate on building scope",
        )
        self.assertIn("building_id", body)

    def test_inventory_marks_presets_tenant_building_acl(self):
        inv = ROOT / "scripts" / "security" / "inventory" / "routes.json"
        data = inv.read_text(encoding="utf-8")
        self.assertIn("/api/analytics/rcx/presets", data)
        self.assertIn("a_foreign_analytics_rcx_presets_denied", data)


if __name__ == "__main__":
    unittest.main()
