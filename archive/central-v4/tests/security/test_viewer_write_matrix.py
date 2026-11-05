"""Viewer write matrix: status AND persisted side effect decide each cell."""
from __future__ import annotations

import io
import json
import sys
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/security"))

from openfdd_security.config import FixtureRefs  # noqa: E402
from openfdd_security.suites import (  # noqa: E402
    SuiteContext,
    run_viewer_write_matrix,
    viewer_probe_package,
    viewer_write_check_ids,
)
from openfdd_security.transport import TransportError  # noqa: E402

DENY = json.dumps({"ok": False, "error": "operator or admin role required"}).encode()


class FakeClient:
    """Owner GETs return a state blob; viewer writes follow ``write_status``."""

    def __init__(self, write_status=403, write_body=DENY, mutate=False, owner_get_status=200, fail_on=None):
        self.write_status = write_status
        self.write_body = write_body
        self.mutate = mutate
        self.owner_get_status = owner_get_status
        self.fail_on = fail_on
        self.state = {"BUILDING_A": 0, "BUILDING_B": 0}
        self.writes: list[tuple[str, str]] = []

    def request(self, method, path, *, token=None, headers=None, body=None, json_body=None, **_):
        if self.fail_on and self.fail_on in path and method != "GET":
            raise TransportError("transport fault: timeout")
        if method == "GET":
            bid = "BUILDING_A" if "BUILDING_A" in path else "BUILDING_B"
            return SimpleNamespace(
                status=self.owner_get_status,
                body=json.dumps({"datasets": [{"id": bid, "gen": self.state[bid]}]}).encode(),
            )
        self.writes.append((method, path))
        if json_body is not None:
            bid = json_body["building_id"]
        elif body:
            with zipfile.ZipFile(io.BytesIO(body)) as zf:
                bid = json.loads(zf.read("manifest.json"))["building_id"]
        else:
            bid = "BUILDING_A" if "BUILDING_A" in path else "BUILDING_B"
        if self.mutate:
            self.state[bid] += 1
        return SimpleNamespace(status=self.write_status, body=self.write_body)


def _run(client, *, profile="isolated_full", writes=True, viewer=True, tok_b="tok-b"):
    results = []
    cfg = SimpleNamespace(fixtures=FixtureRefs(), identities={})
    ctx = SuiteContext(client, cfg, profile, results.append, allow_fixture_writes=writes)
    run_viewer_write_matrix(ctx, "tok-viewer" if viewer else None, "tok-a", tok_b, viewer)
    return {c.check_id: c for c in results}


class ViewerWriteMatrixTest(unittest.TestCase):
    def test_check_ids_cover_actions_and_scopes(self):
        ids = viewer_write_check_ids()
        self.assertEqual(len(ids), 8)
        for action in ("import", "append", "purge", "delete"):
            for scope in ("own", "foreign"):
                self.assertIn(f"y.authz.viewer_{action}_{scope}_denied", ids)

    def test_structured_403_without_side_effect_passes(self):
        client = FakeClient()
        checks = _run(client)
        self.assertEqual({c.status for c in checks.values()}, {"PASS"})
        self.assertEqual(len(client.writes), 8)
        methods = sorted({m for m, _ in client.writes})
        self.assertEqual(methods, ["DELETE", "POST"])
        self.assertTrue(any("building_id=" in p for _, p in client.writes))
        self.assertTrue(any("id=" in p and "building_id" not in p for _, p in client.writes))

    def test_accepted_write_fails(self):
        checks = _run(FakeClient(write_status=200, write_body=b'{"ok":true}'))
        for c in checks.values():
            self.assertEqual(c.status, "FAIL")
            self.assertEqual(c.detector_id, "viewer_write_allowed")

    def test_403_with_persisted_change_fails(self):
        checks = _run(FakeClient(mutate=True))
        for c in checks.values():
            self.assertEqual(c.status, "FAIL")
            self.assertEqual(c.detector_id, "viewer_write_side_effect")

    def test_401_is_not_role_proof(self):
        checks = _run(FakeClient(write_status=401, write_body=b'{"ok":false}'))
        self.assertEqual({c.status for c in checks.values()}, {"ERROR"})

    def test_unstructured_403_fails(self):
        checks = _run(FakeClient(write_body=b"<html>forbidden</html>"))
        self.assertEqual({c.status for c in checks.values()}, {"FAIL"})

    def test_foreign_404_deny_passes_own_404_fails(self):
        checks = _run(FakeClient(write_status=404, write_body=b'{"ok":false}'))
        for cid, c in checks.items():
            self.assertEqual(c.status, "PASS" if cid.endswith("_foreign_denied") else "FAIL", cid)

    def test_unobservable_owner_state_blocks(self):
        client = FakeClient(owner_get_status=403)
        checks = _run(client)
        self.assertEqual({c.status for c in checks.values()}, {"BLOCKED"})
        self.assertEqual(client.writes, [])

    def test_missing_foreign_owner_blocks_foreign_only(self):
        checks = _run(FakeClient(), tok_b=None)
        for cid, c in checks.items():
            self.assertEqual(c.status, "BLOCKED" if cid.endswith("_foreign_denied") else "PASS", cid)

    def test_unconfirmed_viewer_blocks_without_writes(self):
        client = FakeClient()
        checks = _run(client, viewer=False)
        self.assertEqual({c.status for c in checks.values()}, {"BLOCKED"})
        self.assertEqual(client.writes, [])

    def test_live_readonly_is_not_applicable_and_sends_nothing(self):
        client = FakeClient()
        checks = _run(client, profile="live_readonly", writes=False)
        self.assertEqual({c.status for c in checks.values()}, {"NOT_APPLICABLE"})
        self.assertEqual(client.writes, [])

    def test_isolated_without_write_flag_blocks(self):
        client = FakeClient()
        checks = _run(client, writes=False)
        self.assertEqual({c.status for c in checks.values()}, {"BLOCKED"})
        self.assertEqual(client.writes, [])

    def test_transport_fault_is_error(self):
        checks = _run(FakeClient(fail_on="/api/csv/import/package"))
        self.assertEqual(checks["y.authz.viewer_import_own_denied"].status, "ERROR")
        self.assertEqual(checks["y.authz.viewer_purge_own_denied"].status, "PASS")

    def test_probe_package_is_valid_openfdd_package(self):
        raw = viewer_probe_package("SITE_X")
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            names = sorted(zf.namelist())
            manifest = json.loads(zf.read("manifest.json"))
        self.assertEqual(manifest["schema_version"], "openfdd_package_v1")
        self.assertEqual(manifest["building_id"], "SITE_X")
        self.assertIn("QA_VIEWER_PROBE/history_wide.csv", names)
        self.assertEqual(raw, viewer_probe_package("SITE_X"))


if __name__ == "__main__":
    unittest.main()
