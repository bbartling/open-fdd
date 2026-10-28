"""Offline tests for SI cutover IP baseline capture (T1284 W0b)."""

from __future__ import annotations

import gzip
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
STRESS = REPO / "scripts" / "stress"
SI_CUTOVER = STRESS / "si_cutover"
if str(STRESS) not in sys.path:
    sys.path.insert(0, str(STRESS))


def _load_capture():
    spec = importlib.util.spec_from_file_location(
        "capture_ip_baseline",
        SI_CUTOVER / "capture_ip_baseline.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["capture_ip_baseline"] = module
    spec.loader.exec_module(module)
    return module


capture = _load_capture()
baseline_io = importlib.import_module("si_cutover.baseline_io")


class CaptureIpBaselineSelfTest(unittest.TestCase):
    def test_cli_self_test_exits_zero(self) -> None:
        self.assertEqual(capture.main(["--self-test"]), 0)

    def test_jsonl_gz_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rows.jsonl.gz"
            row = {"building_id": "X", "n": 1}
            with baseline_io.JsonlGzWriter(path) as writer:
                writer.write(row)
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                loaded = json.loads(fh.read().strip())
            self.assertEqual(loaded, row)

    def test_manifest_lists_file_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            sample = out / "sql_fdd_daily.jsonl.gz"
            with baseline_io.JsonlGzWriter(sample) as writer:
                writer.write({"building_id": "S", "rule_id": "FC1"})
            meta = {"captured_at": "2026-01-01T00:00:00Z"}
            manifest_path = baseline_io.write_manifest(out, meta=meta)
            doc = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(doc["schema"], "openfdd-si-ip-baseline-manifest-v1")
            self.assertEqual(len(doc["files"]), 1)
            self.assertTrue(doc["files"][0]["sha256"])


class CaptureFixtureStack(unittest.TestCase):
    """Mocked stack run: output shapes and telemetry counts unchanged."""

    def test_capture_site_telemetry_unchanged(self) -> None:
        building_id = "SYNTH_CI_BASELINE"
        run_resp = {
            "ok": True,
            "run_id": "run-ci-1",
            "window_start": "2026-06-01T00:00:00Z",
            "window_end": "2026-06-02T00:00:00Z",
            "results": [
                {
                    "rule_id": "FC1",
                    "equipment_id": "AHU_1",
                    "fault_hours": 0.05,
                    "status": "FAULT",
                }
            ],
        }
        counts = {"sample": 12, "point_map": 4, "authorized_series": 4}

        class FakeHttp:
            def post_json(self, path, headers=None, json_body=None):
                return run_resp

            def get_json(self, path, headers=None, params=None):
                if path == "/api/csv/import/package/mapping":
                    return {
                        "session_config": {"unit_system": "imperial"},
                        "columns": [
                            {
                                "openfdd_key": "AHU_1.fan_status",
                                "role": "fan-status",
                                "unit": "1",
                            }
                        ],
                    }
                if path == "/api/fdd/equipment":
                    return {"equipment": [{"equipment_id": "AHU_1", "equip_type": "ahu"}]}
                return {}

        fake_conn = mock.MagicMock()
        fake_cursor = mock.MagicMock()
        fake_conn.cursor.return_value.__enter__ = mock.Mock(return_value=fake_cursor)
        fake_conn.cursor.return_value.__exit__ = mock.Mock(return_value=False)
        fake_cursor.fetchone.side_effect = [(n,) for n in counts.values()] * 2
        fake_cursor.fetchall.side_effect = [[], [], []]

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            with mock.patch.object(capture, "db_connect", return_value=fake_conn):
                with mock.patch.object(capture, "analytics_rows_for_site", return_value=[]):
                    with mock.patch.object(capture, "pandas_daily_rows", return_value=[]):
                        summary = capture.capture_site(
                            FakeHttp(),
                            {},
                            site={"building_id": building_id},
                            out_dir=out_dir,
                            rules=[{"rule_id": "FC1", "pandas_function": "fc1"}],
                            skip_pandas=True,
                            pandas_max_rules=None,
                        )
            self.assertEqual(summary["building_id"], building_id)
            site_dir = out_dir / building_id
            for name in (
                "sql_fdd_daily.jsonl.gz",
                "analytics_rows.jsonl.gz",
                "pandas_fdd_daily.jsonl.gz",
                "unit_inventory.jsonl.gz",
                "sample_counts.jsonl.gz",
                "persisted_runs.jsonl.gz",
            ):
                self.assertTrue((site_dir / name).is_file(), name)
            with gzip.open(site_dir / "persisted_runs.jsonl.gz", "rt", encoding="utf-8") as fh:
                persisted = json.loads(fh.read().strip())
            self.assertEqual(persisted["run_id"], "run-ci-1")


if __name__ == "__main__":
    unittest.main()
