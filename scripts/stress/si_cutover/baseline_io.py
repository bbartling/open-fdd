"""JSONL.gz writers and manifest helpers for IP baseline capture."""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MANIFEST_SCHEMA = "openfdd-si-ip-baseline-manifest-v1"

MANDATORY_SITE_ARTIFACTS: tuple[str, ...] = (
    "sql_fdd_daily.jsonl.gz",
    "pandas_fdd_daily.jsonl.gz",
    "analytics_rows.jsonl.gz",
    "unit_inventory.jsonl.gz",
    "sample_counts.jsonl.gz",
    "persisted_runs.jsonl.gz",
)


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


def manifest_entry_tier(relative_posix: str) -> str:
    name = Path(relative_posix).name
    if name in MANDATORY_SITE_ARTIFACTS:
        return "mandatory"
    return "ancillary"


def write_manifest(out_dir: Path, *, meta: dict[str, Any]) -> Path:
    """Write a root manifest covering all files under ``out_dir`` (site subdirs included)."""
    files: list[dict[str, Any]] = []
    for path in sorted(out_dir.rglob("*")):
        if not path.is_file() or path.name == "manifest.sha256.json":
            continue
        rel = path.relative_to(out_dir).as_posix()
        files.append(
            {
                "name": rel,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "tier": manifest_entry_tier(rel),
            }
        )
    manifest = {"schema": MANIFEST_SCHEMA, "meta": meta, "files": files}
    manifest_path = out_dir / "manifest.sha256.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def _site_window_from_meta(meta: dict[str, Any], building_id: str) -> tuple[str, str]:
    if str(meta.get("building_id") or "") == building_id:
        ws = str(meta.get("window_start") or meta.get("requested_window_start") or "")
        we = str(meta.get("window_end") or meta.get("requested_window_end") or "")
        return ws, we
    for site in meta.get("sites") or []:
        if not isinstance(site, dict):
            continue
        if str(site.get("building_id") or "") != building_id:
            continue
        ws = str(
            site.get("window_start")
            or site.get("effective_window_start")
            or site.get("requested_window_start")
            or ""
        )
        we = str(
            site.get("window_end")
            or site.get("effective_window_end")
            or site.get("requested_window_end")
            or ""
        )
        return ws, we
    return "", ""


def _validate_manifest_files(
    manifest: dict[str, Any],
    base_dir: Path,
    *,
    building_id: str | None,
    site_relative_prefix: str | None,
) -> list[str]:
    """Strict file list + digest validation."""
    errors: list[str] = []
    if manifest.get("schema") != MANIFEST_SCHEMA:
        errors.append(f"manifest schema must be {MANIFEST_SCHEMA}")
    files = manifest.get("files")
    if not isinstance(files, list):
        errors.append("manifest files must be a list")
        return errors
    if not files:
        errors.append("manifest files list empty")
        return errors

    listed_names: set[str] = set()
    mandatory_in_manifest: set[str] = set()
    for entry in files:
        if not isinstance(entry, dict):
            errors.append("manifest file entry must be an object")
            continue
        name = str(entry.get("name") or "")
        if not name:
            errors.append("manifest file entry missing name")
            continue
        listed_names.add(name)
        expected = str(entry.get("sha256") or "")
        if not expected:
            errors.append(f"manifest entry {name} missing sha256 digest")
        tier = str(entry.get("tier") or manifest_entry_tier(name))
        if tier == "mandatory":
            mandatory_in_manifest.add(name)
        path = base_dir / name
        if not path.is_file():
            errors.append(f"manifest lists missing file {name}")
            continue
        actual = sha256_file(path)
        if not expected:
            continue
        if actual != expected:
            errors.append(f"manifest hash mismatch for {name}")
        size = entry.get("bytes")
        if size is not None and int(size) != path.stat().st_size:
            errors.append(f"manifest size mismatch for {name}")

    if building_id and site_relative_prefix is None:
        prefix = f"{building_id}/"
        for artifact in MANDATORY_SITE_ARTIFACTS:
            rel = f"{prefix}{artifact}"
            if rel not in listed_names:
                errors.append(f"mandatory artifact omitted from manifest: {rel}")
            elif rel not in mandatory_in_manifest and rel in listed_names:
                errors.append(f"mandatory artifact {rel} not marked mandatory tier")
            if not (base_dir / rel).is_file():
                errors.append(f"mandatory artifact missing on disk: {rel}")
    elif site_relative_prefix == "":
        for artifact in MANDATORY_SITE_ARTIFACTS:
            if artifact not in listed_names:
                errors.append(f"mandatory artifact omitted from manifest: {artifact}")
            elif artifact not in mandatory_in_manifest:
                errors.append(f"mandatory artifact {artifact} not marked mandatory tier")
            if not (base_dir / artifact).is_file():
                errors.append(f"mandatory artifact missing on disk: {artifact}")
    elif site_relative_prefix is None and building_id is None:
        for entry in files:
            name = str(entry.get("name") or "")
            if Path(name).name in MANDATORY_SITE_ARTIFACTS and name not in mandatory_in_manifest:
                errors.append(f"mandatory site artifact {name} not marked mandatory tier")

    return errors


def verify_site_manifest(site_dir: Path) -> tuple[dict[str, Any], list[str]]:
    """Verify a per-site manifest (legacy mini-fixture layout)."""
    manifest_path = site_dir / "manifest.sha256.json"
    if not manifest_path.is_file():
        return {}, [f"missing manifest {manifest_path}"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {}, [f"manifest JSON invalid: {exc}"]
    meta = manifest.get("meta") if isinstance(manifest.get("meta"), dict) else {}
    site_building = str(meta.get("building_id") or site_dir.name)
    errors = _validate_manifest_files(
        manifest, site_dir, building_id=site_building, site_relative_prefix=""
    )
    return manifest, errors


def verify_baseline_for_p3(
    baseline_dir: Path,
    *,
    building_id: str,
    expected_window_start: str | None = None,
    expected_window_end: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Validate W0c-style root manifest (preferred) or strict per-site manifest."""
    root_manifest_path = baseline_dir / "manifest.sha256.json"
    site_dir = baseline_dir / building_id
    if root_manifest_path.is_file():
        try:
            manifest = json.loads(root_manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return {}, [f"root manifest JSON invalid: {exc}"]
        errors = _validate_manifest_files(
            manifest, baseline_dir, building_id=building_id, site_relative_prefix=None
        )
        meta = manifest.get("meta") if isinstance(manifest.get("meta"), dict) else {}
        window_start, window_end = _site_window_from_meta(meta, building_id)
    elif (site_dir / "manifest.sha256.json").is_file():
        manifest, errors = verify_site_manifest(site_dir)
        meta = manifest.get("meta") if isinstance(manifest.get("meta"), dict) else {}
        window_start, window_end = _site_window_from_meta(meta, building_id)
    else:
        return {}, [f"missing baseline manifest under {baseline_dir}"]

    if not window_start:
        errors.append("manifest missing window_start for site")
    if not window_end:
        errors.append("manifest missing window_end for site")
    if expected_window_start:
        if not window_start:
            errors.append(
                f"P3 expected window_start {expected_window_start} but manifest has no window_start"
            )
        elif window_start != expected_window_start:
            errors.append(
                f"P3 window_start mismatch: expected {expected_window_start} manifest {window_start}"
            )
    if expected_window_end:
        if not window_end:
            errors.append(
                f"P3 expected window_end {expected_window_end} but manifest has no window_end"
            )
        elif window_end != expected_window_end:
            errors.append(
                f"P3 window_end mismatch: expected {expected_window_end} manifest {window_end}"
            )
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
