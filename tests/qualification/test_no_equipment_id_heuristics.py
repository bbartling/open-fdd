"""Fail closed when product code grows an equipment_id LIKE / id-text selector.

Run: python3 -B -m unittest discover -s tests/qualification -v

This is the in-repo prove path for #1037–#1042 and #1045–#1047. It does not
claim tip+field stress or fully_qualified.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts/qualification/no_equipment_id_heuristics.py"
)
SPEC = importlib.util.spec_from_file_location("no_equipment_id_heuristics", MODULE_PATH)
gate = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(gate)


class NoEquipmentIdHeuristicsTest(unittest.TestCase):
    def test_repo_source_has_no_id_text_selectors(self):
        findings = gate.scan(Path(__file__).resolve().parents[2])
        self.assertEqual(findings, [], "\n".join(findings))

    def test_selftest_flags_like_and_ignores_negation(self):
        self.assertEqual(gate.selftest(), 0)

    def test_picker_uses_stamp_not_id_letters(self):
        records = [
            {"equipment_id": "AHU_GHOST", "equipment_type": "VAV"},
            {"equipment_id": "RTU_010", "equipment_type": "AHU"},
            {"equipment_id": "RTU_01", "equipment_type_raw": "vav"},
            {"equipment_id": "AC_1", "equipType": "ahu"},
            {"equipment_id": "bldg2-zone-loopback"},
        ]
        self.assertEqual(gate.pick_equipment_id(records, "ahu"), "AC_1")
        # AHU_GHOST is stamped VAV, so it is the VAV pick. RTU_010 stays AHU.
        self.assertEqual(gate.pick_equipment_id(records, "vav"), "AHU_GHOST")
        self.assertEqual(gate.kind_of_record(records[1]), "ahu")
        self.assertEqual(gate.canonical_kind("CHILLER_HEAT_PUMP"), None)
        self.assertEqual(gate.canonical_kind("chiller"), "chiller")
        self.assertEqual(gate.canonical_kind("heatPump"), "heatpump")
        self.assertIsNone(gate.kind_of_record({"equipment_id": "OA_REF"}))
        self.assertEqual(
            gate.kind_of_record(
                {"equipment_id": "OA_REF", "equipment_type_raw": "weather"}
            ),
            "weather",
        )

    def test_preset_membership_fails_closed_on_contradictory_stamps(self):
        inventory = [
            {"equipment_id": "AC_1", "equipment_type_raw": "ahu"},
            {"equipment_id": "jci_vav_1", "equipType": "vav"},
            {"equipment_id": "jci_ahu_1", "equipment_type": "AHU"},
            {"equipment_id": "AHU_BOX", "equipment_type": "VAV"},
            {"equipment_id": "bldg2-zone-loopback"},
        ]
        self.assertEqual(
            gate.check_preset_membership(
                "ahu",
                {"points": [{"equipment_id": "AC_1"}, {"equipment_id": "jci_ahu_1"}]},
                inventory,
            ),
            [],
        )
        ahu_bad = gate.check_preset_membership(
            "ahu",
            {"points": [{"equipment_id": "AHU_BOX"}]},
            inventory,
        )
        self.assertTrue(any("AHU_BOX" in item for item in ahu_bad))
        self.assertEqual(
            gate.check_preset_membership(
                "zone",
                {"rows": [{"equipment_id": "jci_vav_1"}]},
                inventory,
            ),
            [],
        )
        zone_bad = gate.check_preset_membership(
            "zone",
            {"analytics": {"points": [{"equipment_id": "AC_1"}]}},
            inventory,
        )
        self.assertTrue(zone_bad)
        like_bad = gate.check_preset_membership(
            "ahu",
            {"sql": "WHERE equipment_id ILIKE '%weather%'"},
            inventory,
        )
        self.assertTrue(any("LIKE" in item for item in like_bad))


if __name__ == "__main__":
    unittest.main()
