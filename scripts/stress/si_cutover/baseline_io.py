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


def verify_site_manifest(site_dir: Path) -> tuple[dict[str, Any], list[str]]:
    """Verify manifest.sha256.json matches on-disk baseline files for one site dir."""
    errors: list[str] = []
    manifest_path = site_dir / "manifest.sha256.json"
    if not manifest_path.is_file():
        return {}, [f"missing manifest {manifest_path}"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {}, [f"manifest JSON invalid: {exc}"]
    if manifest.get("schema") != "openfdd-si-ip-baseline-manifest-v1":
        errors.append("manifest schema must be openfdd-si-ip-baseline-manifest-v1")
    files = manifest.get("files")
    if not isinstance(files, list):
        errors.append("manifest files must be a list")
        return manifest, errors
    for entry in files:
        if not isinstance(entry, dict):
            errors.append("manifest file entry must be an object")
            continue
        name = str(entry.get("name") or "")
        expected = str(entry.get("sha256") or "")
        path = site_dir / name
        if not path.is_file():
            errors.append(f"manifest lists missing file {name}")
            continue
        actual = sha256_file(path)
        if expected and actual != expected:
            errors.append(f"manifest hash mismatch for {name}")
        size = entry.get("bytes")
        if size is not None and int(size) != path.stat().st_size:
            errors.append(f"manifest size mismatch for {name}")
    return manifest, errors


def validate_fdd_daily_row(row: dict[str, Any]) -> list[str]:
    """Return field/shape errors for one sql_fdd_daily / live row."""
    errors: list[str] = []
    for key in ("building_id", "rule_id", "equipment_id", "utc_day", "status"):
        if not str(row.get(key, "")).strip():
            errors.append(f"missing {key}")
    for field in ("fault_seconds", "covered_seconds"):
        val = row.get(field)
        if val is None:
            errors.append(f"missing {field}")
            continue
        try:
            num = float(val)
        except (TypeError, ValueError):
            errors.append(f"non-numeric {field}")
            continue
        if num != num or num in (float("inf"), float("-inf")):
            errors.append(f"non-finite {field}")
        if num < 0:
            errors.append(f"negative {field}")
    return errors


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
