"""Inventory honesty + drift CI enforcement."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/security"))

from openfdd_security.inventory import (  # noqa: E402
    POLICY_SOURCE,
    find_uninventoried_routes,
    inventory_integrity_errors,
    inventory_summary,
    load_cross_cutting_checks,
    load_implemented_checks,
    load_inventory,
    profile_required_drift_errors,
)
from openfdd_security.profiles import load_profile_required, required_check_ids  # noqa: E402

ROUTES_RS = ROOT / "services" / "central" / "src" / "routes.rs"


class InventoryIntegrityTest(unittest.TestCase):
    def test_no_integrity_errors(self):
        errs = inventory_integrity_errors()
        self.assertEqual(errs, [], msg="\n".join(errs))

    def test_no_uninventoried_routes_rs(self):
        missing = find_uninventoried_routes(ROUTES_RS)
        self.assertEqual(missing, [], msg=f"uninventoried: {missing}")

    def test_disposition_counts_honest(self):
        inv = load_inventory()
        s = inventory_summary(inv)
        self.assertNotIn("COVERED", s["disposition_counts"])
        self.assertGreater(s["planned"], 0)
        self.assertGreaterEqual(s["implemented"], 1)
        self.assertLess(s["implemented"], s["planned"])

    def test_implemented_registry_nonempty(self):
        ids = load_implemented_checks()
        self.assertGreaterEqual(len(ids), 10)
        self.assertTrue(any(i.startswith("x.") for i in ids))
        self.assertTrue(any(i.startswith("y.") for i in ids))

    def test_policy_source_single_inventory(self):
        inv = load_inventory()
        self.assertEqual(inv.get("policy_source"), POLICY_SOURCE)

    def test_profile_required_loaded_from_inventory_json(self):
        profiles = load_profile_required()
        self.assertIn("live_readonly", profiles)
        self.assertIn(
            "x.preauth.health_public",
            required_check_ids("live_readonly", ["X"]),
        )

    def test_profile_required_no_drift(self):
        errs = profile_required_drift_errors()
        self.assertEqual(errs, [], msg="\n".join(errs))

    def test_cross_cutting_registry_nonempty(self):
        ids = load_cross_cutting_checks()
        self.assertGreaterEqual(len(ids), 10)
        self.assertIn("x.jwt.missing_token_401", ids)


if __name__ == "__main__":
    unittest.main()
