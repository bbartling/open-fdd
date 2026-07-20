"""Assemble multiple browser-upload zip parts into one openfdd_package_v1 session.

Humans (and Cloud) are limited by Streamlit ``maxUploadSize`` per file (~500 MB).
A full job may be up to ``DEFAULT_PACKAGE_MB`` (2 GB) uncompressed once merged.
Agents preprocess CSVs into several part zips; this module merges them safely.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import BinaryIO

from app.package_io import (
    TEMP_PREFIX,
    PackageCaps,
    PackageError,
    PackageLoadResult,
    _BACKSLASH_ZIP_HINT,
    _ensure_parent_dir,
    _inspect_zip,
    _is_zip_dir,
    _safe_member_path,
    _zip_has_backslash_paths,
    absorb_sibling_weather,
    effective_package_caps,
    load_package_from_dir,
    wipe_workdir,
)

JOB_SCHEMA = "openfdd_job_v1"


@dataclass
class ZipPart:
    name: str
    data: bytes


def _extract_part_into(workdir: Path, data: bytes, *, caps: PackageCaps, part_name: str) -> list[str]:
    """Extract one zip into workdir. Returns warnings (e.g. overwrites)."""
    warnings: list[str] = []
    if len(data) > caps.max_zip_bytes:
        # Per-part still checked against browser cap when caller passes browser_caps
        raise PackageError(
            f"{part_name}: zip exceeds {caps.max_zip_mb} MB per-file upload limit"
        )
    try:
        with zipfile.ZipFile(BytesIO(data), "r") as zf:
            _inspect_zip(zf, caps)
            for info in zf.infolist():
                if _is_zip_dir(info):
                    continue
                rel = _safe_member_path(info.filename)
                if not rel.parts:
                    continue
                target = workdir / rel
                if target.is_file():
                    warnings.append(
                        f"{part_name}: overwriting existing path `{rel.as_posix()}`"
                    )
                _ensure_parent_dir(target, info.filename)
                with zf.open(info, "r") as src, target.open("wb") as out:
                    while True:
                        chunk = src.read(1024 * 256)
                        if not chunk:
                            break
                        out.write(chunk)
    except PackageError:
        raise
    except zipfile.BadZipFile as exc:
        raise PackageError(f"{part_name}: not a valid zip ({exc})") from exc
    except OSError as exc:
        hint = ""
        try:
            with zipfile.ZipFile(BytesIO(data), "r") as _zf:
                if _zip_has_backslash_paths(_zf):
                    hint = f" {_BACKSLASH_ZIP_HINT}"
        except Exception:
            pass
        raise PackageError(f"{part_name}: extraction failed ({exc}).{hint}") from exc
    return warnings


def _normalize_parts(parts: list[ZipPart]) -> tuple[list[ZipPart], list[str]]:
    if not parts:
        raise PackageError("No zip parts provided")
    warnings: list[str] = []
    # Drop accidental duplicate uploads (same filename or identical bytes)
    deduped: list[ZipPart] = []
    seen_name: set[str] = set()
    seen_hash: set[str] = set()
    for p in parts:
        key = p.name.lower().strip()
        digest = hashlib.sha256(p.data).hexdigest()
        if key in seen_name or digest in seen_hash:
            warnings.append(f"Skipping duplicate upload `{p.name}`")
            continue
        seen_name.add(key)
        seen_hash.add(digest)
        deduped.append(p)
    if not deduped:
        raise PackageError("No zip parts provided after removing duplicates")

    def sort_key(p: ZipPart) -> tuple:
        n = p.name.lower()
        for token in ("part0", "part1", "part2", "part3", "part4", "part5", "part6", "part7", "part8", "part9"):
            if token in n:
                return (0, n)
        if "manifest" in n or n.endswith("job.json"):
            return (-1, n)
        # Building packages before weather sidecars
        if "weather" in n and "building" not in n:
            return (2, n)
        return (1, n)

    return sorted(deduped, key=sort_key), warnings


def merge_zip_parts_to_dir(
    parts: list[ZipPart],
    *,
    caps: PackageCaps | None = None,
    per_part_caps: PackageCaps | None = None,
) -> tuple[Path, list[str]]:
    """Extract all parts into a fresh temp dir. Returns (workdir, warnings)."""
    caps = caps or effective_package_caps()
    per_part = per_part_caps or caps
    ordered, warnings = _normalize_parts(parts)
    total = sum(len(p.data) for p in ordered)
    # Soft check: compressed sum should not wildly exceed agent cap
    if total > caps.max_uncompressed_bytes:
        raise PackageError(
            f"Combined zip parts are {total / (1024 * 1024):.0f} MB compressed — "
            f"exceeds {caps.max_uncompressed_mb} MB safety limit"
        )
    workdir = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))
    try:
        for part in ordered:
            warnings.extend(
                _extract_part_into(workdir, part.data, caps=per_part, part_name=part.name)
            )
        from app.package_io import expand_nested_zips

        warnings.extend(expand_nested_zips(workdir, caps=caps))
        # Optional job manifest validation
        job_path = workdir / "job_manifest.json"
        if job_path.is_file():
            try:
                job = json.loads(job_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise PackageError(f"job_manifest.json invalid JSON: {exc}") from exc
            ver = str(job.get("schema_version") or "")
            if ver and ver != JOB_SCHEMA:
                warnings.append(
                    f"job_manifest.json schema_version={ver!r} (expected {JOB_SCHEMA}) — continuing"
                )
            expected = job.get("parts") or job.get("zip_parts")
            if isinstance(expected, list) and expected:
                got = {p.name for p in ordered}
                missing = [str(x) for x in expected if str(x) not in got]
                if missing:
                    warnings.append(
                        f"job_manifest lists parts not uploaded: {', '.join(missing[:8])}"
                    )
        return workdir, warnings
    except Exception:
        wipe_workdir(workdir)
        raise


def load_package_from_zip_parts(
    parts: list[ZipPart],
    *,
    merge_caps: PackageCaps | None = None,
    per_part_caps: PackageCaps | None = None,
) -> PackageLoadResult:
    """Merge zip parts then ``load_package_from_dir`` (full agent-size cap on result)."""
    merge_caps = merge_caps or effective_package_caps()
    per_part_caps = per_part_caps or effective_package_caps(for_browser_upload=True)
    workdir, merge_warnings = merge_zip_parts_to_dir(
        parts, caps=merge_caps, per_part_caps=per_part_caps
    )
    try:
        from app.package_io import resolve_building_root

        building_root = resolve_building_root(workdir)
        merge_warnings.extend(absorb_sibling_weather(building_root, workdir))
        result = load_package_from_dir(building_root, workdir=workdir, caps=merge_caps)
        result.warnings = list(merge_warnings) + list(result.warnings)
        result.report["source"] = "multi_zip"
        result.report["zip_part_count"] = len(parts)
        result.report["zip_part_names"] = [p.name for p in parts]
        result.report["zip_parts_bytes"] = sum(len(p.data) for p in parts)
        result.report["zip_parts_mb"] = round(
            sum(len(p.data) for p in parts) / (1024 * 1024), 3
        )
        return result
    except Exception:
        wipe_workdir(workdir)
        raise


def parts_from_uploads(files: list) -> list[ZipPart]:
    """Build ZipPart list from Streamlit UploadedFile-like objects."""
    out: list[ZipPart] = []
    for f in files:
        name = getattr(f, "name", None) or "part.zip"
        data = f.getvalue() if hasattr(f, "getvalue") else bytes(f.read())
        out.append(ZipPart(name=str(name), data=data))
    return out
