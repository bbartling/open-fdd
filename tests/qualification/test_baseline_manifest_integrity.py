"""W0c baseline manifest round-trip and negative controls (SQL407 / Codex gap 1)."""

from __future__ import annotations

import gzip
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
STRESS = REPO / "scripts" / "stress"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class BaselineManifestIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bio = _load("bio_manifest", STRESS / "si_cutover" / "baseline_io.py")
        cls.pc = _load("pc_manifest", STRESS / "si_cutover" / "parity_chain.py")
        cls.capture = _load("cap_manifest", STRESS / "si_cutover" / "capture_ip_baseline.py")

    def _write_min_site_tree(self, root: Path, *, building_id: str = "SITE_A") -> Path:
        site = root / building_id
        site.mkdir(parents=True, exist_ok=True)
        row = {
            "building_id": building_id,
            "rule_id": "FC1",
            "equipment_id": "E1",
            "utc_day": "2026-06-01",
            "fault_seconds": 300.0,
            "covered_seconds": 600.0,
            "status": "FAULT",
        }
        for name in self.bio.MANDATORY_SITE_ARTIFACTS:
            path = site / name
            with self.bio.JsonlGzWriter(path) as writer:
                if name == "sql_fdd_daily.jsonl.gz":
                    writer.write(row)
                elif name == "pandas_fdd_daily.jsonl.gz":
                    writer.write({**row, "pair_status": "computed", "reason": ""})
                elif name == "sample_counts.jsonl.gz":
                    writer.write({"building_id": building_id, "table": "sample", "row_count": 1})
                elif name == "persisted_runs.jsonl.gz":
                    writer.write(
                        {
                            "building_id": building_id,
                            "run_id": "run-1",
                            "window_start": "2026-06-01T00:00:00Z",
                            "window_end": "2026-06-02T00:00:00Z",
                        }
                    )
                elif name == "analytics_rows.jsonl.gz":
                    writer.write(
                        {
                            "building_id": building_id,
                            "endpoint": "/api/analytics/runtime",
                            "row": {"ok": True},
                        }
                    )
                elif name == "unit_inventory.jsonl.gz":
                    writer.write(
                        {
                            "building_id": building_id,
                            "openfdd_key": "E1.fc",
                            "role": "fan-status",
                            "inventory_status": "ok",
                            "point_map_unit": "1",
                            "sample_unit": "1",
                            "package_unit_system": "imperial",
                            "w2c_source_unit": "imperial",
                        }
                    )
        return site

    def test_capture_shaped_root_manifest_round_trips_p3(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            building_id = "SITE_A"
            self._write_min_site_tree(root, building_id=building_id)
            meta = {
                "captured_at": "2026-06-01T12:00:00Z",
                "sites": [
                    {
                        "building_id": building_id,
                        "window_start": "2026-06-01T00:00:00Z",
                        "window_end": "2026-06-02T00:00:00Z",
                    }
                ],
            }
            self.bio.write_manifest(root, meta=meta)
            manifest, errors = self.bio.verify_baseline_for_p3(
                root,
                building_id=building_id,
                expected_window_start="2026-06-01T00:00:00Z",
                expected_window_end="2026-06-02T00:00:00Z",
            )
            self.assertFalse(errors, errors)
            live_row = {
                "building_id": building_id,
                "rule_id": "FC1",
                "equipment_id": "E1",
                "utc_day": "2026-06-01",
                "fault_seconds": 300,
                "covered_seconds": 600,
                "status": "FAULT",
            }
            result = self.pc.compare_p3_post_cutover(
                baseline_dir=root,
                building_id=building_id,
                live_sql_daily=[live_row],
                live_sample_counts=[{"building_id": building_id, "table": "sample", "row_count": 1}],
                expected_window_start="2026-06-01T00:00:00Z",
                expected_window_end="2026-06-02T00:00:00Z",
            )
            self.assertFalse(result.errors, result.errors)
            self.assertGreaterEqual(result.comparisons, 1)
            self.assertIsInstance(manifest.get("files"), list)

    def test_negative_empty_manifest_files_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            site = self._write_min_site_tree(root)
            manifest_path = root / "manifest.sha256.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema": self.bio.MANIFEST_SCHEMA,
                        "meta": {"sites": [{"building_id": "SITE_A"}]},
                        "files": [],
                    }
                ),
                encoding="utf-8",
            )
            _, errors = self.bio.verify_baseline_for_p3(root, building_id="SITE_A")
            self.assertTrue(any("empty" in e for e in errors))

    def test_negative_missing_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_min_site_tree(root)
            rel = "SITE_A/sql_fdd_daily.jsonl.gz"
            manifest_path = root / "manifest.sha256.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema": self.bio.MANIFEST_SCHEMA,
                        "meta": {
                            "sites": [
                                {
                                    "building_id": "SITE_A",
                                    "window_start": "2026-06-01T00:00:00Z",
                                    "window_end": "2026-06-02T00:00:00Z",
                                }
                            ]
                        },
                        "files": [{"name": rel, "bytes": 1, "sha256": "", "tier": "mandatory"}],
                    }
                ),
                encoding="utf-8",
            )
            _, errors = self.bio.verify_baseline_for_p3(root, building_id="SITE_A")
            self.assertTrue(any("missing sha256" in e for e in errors))

    def test_negative_omitted_mandatory_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_min_site_tree(root)
            (root / "SITE_A" / "pandas_fdd_daily.jsonl.gz").unlink()
            meta = {
                "sites": [
                    {
                        "building_id": "SITE_A",
                        "window_start": "2026-06-01T00:00:00Z",
                        "window_end": "2026-06-02T00:00:00Z",
                    }
                ]
            }
            self.bio.write_manifest(root, meta=meta)
            _, errors = self.bio.verify_baseline_for_p3(root, building_id="SITE_A")
            self.assertTrue(any("mandatory" in e for e in errors))

    def test_negative_tampered_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_min_site_tree(root)
            meta = {
                "sites": [
                    {
                        "building_id": "SITE_A",
                        "window_start": "2026-06-01T00:00:00Z",
                        "window_end": "2026-06-02T00:00:00Z",
                    }
                ]
            }
            self.bio.write_manifest(root, meta=meta)
            path = root / "SITE_A" / "sql_fdd_daily.jsonl.gz"
            with gzip.open(path, "ab") as fh:
                fh.write(b"tamper")
            _, errors = self.bio.verify_baseline_for_p3(root, building_id="SITE_A")
            self.assertTrue(any("hash mismatch" in e for e in errors))

    def test_negative_window_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_min_site_tree(root)
            meta = {
                "sites": [
                    {
                        "building_id": "SITE_A",
                        "window_start": "2026-06-01T00:00:00Z",
                        "window_end": "2026-06-02T00:00:00Z",
                    }
                ]
            }
            self.bio.write_manifest(root, meta=meta)
            _, errors = self.bio.verify_baseline_for_p3(
                root,
                building_id="SITE_A",
                expected_window_start="2026-06-03T00:00:00Z",
            )
            self.assertTrue(any("window_start mismatch" in e for e in errors))

    def test_negative_manifest_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_min_site_tree(root)
            rel = "../outside.txt"
            (root / "outside.txt").write_text("x", encoding="utf-8")
            manifest_path = root / "manifest.sha256.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema": self.bio.MANIFEST_SCHEMA,
                        "meta": {"sites": [{"building_id": "SITE_A"}]},
                        "files": [
                            {
                                "name": rel,
                                "bytes": 1,
                                "sha256": self.bio.sha256_file(root / "outside.txt"),
                                "tier": "ancillary",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            _, errors = self.bio.verify_baseline_for_p3(root, building_id="SITE_A")
            self.assertTrue(any("traverse" in e or "escapes" in e for e in errors))

    def test_negative_manifest_absolute_path(self) -> None:
        errors = self.bio.manifest_path_errors("/etc/passwd", Path("/tmp/base"))
        self.assertTrue(any("absolute" in e for e in errors))

    def test_negative_manifest_symlink_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_min_site_tree(root)
            target = root / "SITE_A" / "sql_fdd_daily.jsonl.gz"
            link = root / "SITE_A" / "evil.jsonl.gz"
            link.symlink_to(target)
            rel = "SITE_A/evil.jsonl.gz"
            manifest_path = root / "manifest.sha256.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema": self.bio.MANIFEST_SCHEMA,
                        "meta": {
                            "sites": [
                                {
                                    "building_id": "SITE_A",
                                    "window_start": "2026-06-01T00:00:00Z",
                                    "window_end": "2026-06-02T00:00:00Z",
                                }
                            ]
                        },
                        "files": [
                            {
                                "name": rel,
                                "bytes": target.stat().st_size,
                                "sha256": self.bio.sha256_file(link),
                                "tier": "mandatory",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            _, errors = self.bio.verify_baseline_for_p3(root, building_id="SITE_A")
            self.assertTrue(any("symlink" in e for e in errors))

    def test_negative_malformed_manifest_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "manifest.sha256.json").write_text("{not-json", encoding="utf-8")
            _, errors = self.bio.verify_baseline_for_p3(root, building_id="SITE_A")
            self.assertTrue(any("JSON invalid" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
