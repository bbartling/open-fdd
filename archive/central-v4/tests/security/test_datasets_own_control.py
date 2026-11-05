import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/security"))

from openfdd_security.suites import _datasets_own_control, _nonempty_own_control


class DatasetOwnControlTests(unittest.TestCase):
    def test_actual_typed_response_requires_exact_requested_site(self):
        body = json.dumps({"ok": True, "datasets": [{
            "id": "BUILDING_A", "building_id": "BUILDING_A", "source": "timescale"
        }]}).encode()
        self.assertTrue(_datasets_own_control(body, "BUILDING_A"))

    def test_empty_datasets_is_not_positive_control(self):
        self.assertFalse(_datasets_own_control(b'{"ok":true,"datasets":[]}', "BUILDING_A"))
        self.assertFalse(_datasets_own_control(b'{"ok":true,"datasets":[]}', ""))

    def test_foreign_only_or_mixed_rows_are_rejected(self):
        foreign = b'{"datasets":[{"id":"BUILDING_B","building_id":"BUILDING_B"}]}'
        mixed = b'{"datasets":[{"id":"BUILDING_A"},{"id":"BUILDING_B"}]}'
        conflicting = b'{"datasets":[{"id":"BUILDING_A","building_id":"BUILDING_B"}]}'
        self.assertFalse(_datasets_own_control(foreign, "BUILDING_A"))
        self.assertFalse(_datasets_own_control(mixed, "BUILDING_A"))
        self.assertFalse(_datasets_own_control(conflicting, "BUILDING_A"))

    def test_malformed_rows_and_generic_objects_are_rejected(self):
        for body in (
            b'{"datasets":[null]}',
            b'{"datasets":[{"dataset_id":"BUILDING_A"}]}',
            b'{"ok":true,"items":[{"id":"BUILDING_A"}]}',
            b'{"ok":true,"data":{"id":"BUILDING_A"}}',
            b'{"ok":false,"datasets":[{"id":"BUILDING_A"}]}',
            b'<html>BUILDING_A</html>',
            b'not json',
        ):
            self.assertFalse(_datasets_own_control(body, "BUILDING_A"), body)

    def test_generic_checker_stays_unchanged_and_does_not_accept_datasets(self):
        body = b'{"ok":true,"datasets":[{"id":"BUILDING_A","building_id":"BUILDING_A"}]}'
        self.assertFalse(_nonempty_own_control(body, "BUILDING_A", require_canary=False))
        self.assertTrue(_datasets_own_control(body, "BUILDING_A"))


if __name__ == "__main__":
    unittest.main()
