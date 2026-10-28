"""JSONL.gz writers and manifest helpers for IP baseline capture."""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, Iterable, TextIO


@dataclass
class JsonlGzWriter:
    path: Path
    _fh: gzip.GzipFile | None = field(default=None, init=False, repr=False)
    line_count: int = field(default=0, init=False)

    def __enter__(self) -> JsonlGzWriter:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = gzip.open(self.path, "wt", encoding="utf-8")
        return self

    def __exit__(self, *exc: object) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def write(self, record: dict[str, Any]) -> None:
        if self._fh is None:
            raise RuntimeError("JsonlGzWriter used outside context manager")
        self._fh.write(json.dumps(record, separators=(",", ":"), sort_keys=True))
        self._fh.write("\n")
        self.line_count += 1


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest(out_dir: Path, *, meta: dict[str, Any]) -> Path:
    files: list[dict[str, Any]] = []
    for path in sorted(out_dir.iterdir()):
        if not path.is_file() or path.name == "manifest.sha256.json":
            continue
        files.append(
            {
                "name": path.name,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    manifest = {"schema": "openfdd-si-ip-baseline-manifest-v1", "meta": meta, "files": files}
    manifest_path = out_dir / "manifest.sha256.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def validate_record_shapes(records: dict[str, list[dict[str, Any]]]) -> list[str]:
    """Return human-readable shape errors (empty list = OK)."""
    errors: list[str] = []
    required_keys = {
        "sql_fdd_daily": {
            "building_id",
            "rule_id",
            "equipment_id",
            "utc_day",
            "fault_seconds",
            "covered_seconds",
            "status",
        },
        "analytics_rows": {"building_id", "endpoint", "row"},
        "pandas_fdd_daily": {
            "building_id",
            "rule_id",
            "equipment_id",
            "utc_day",
            "fault_seconds",
            "covered_seconds",
            "status",
            "pair_status",
            "reason",
        },
        "unit_inventory": {
            "building_id",
            "openfdd_key",
            "role",
            "inventory_status",
            "point_map_unit",
            "sample_unit",
            "package_unit_system",
            "w2c_source_unit",
        },
        "sample_counts": {"building_id", "table", "row_count"},
        "persisted_runs": {"building_id", "run_id", "window_start", "window_end"},
    }
    for kind, keys in required_keys.items():
        rows = records.get(kind) or []
        if not rows:
            errors.append(f"{kind}: expected at least one record in self-test")
            continue
        for index, row in enumerate(rows[:3]):
            missing = keys - set(row.keys())
            if missing:
                errors.append(f"{kind}[{index}] missing keys: {sorted(missing)}")
    return errors
