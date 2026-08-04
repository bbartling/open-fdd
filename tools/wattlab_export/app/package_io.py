"""Safe zip package ingest for Streamlit Cloud / local demos.

See docs/PACKAGE_SPEC.md (openfdd_package_v1).
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field, field_validator

from app.data_loader import discover_equipment, load_equipment_csv, validate_dataframe

SCHEMA_VERSION = "openfdd_package_v1"
SESSION_SCHEMA = "openfdd_session_v1"

# Fixed structural limits (not env-tunable).
MAX_PATH_DEPTH = 8
MAX_COLUMNS = 120
TEMP_PREFIX = "vibe19_"
TEMP_MAX_AGE_SEC = 6 * 3600

# Env overrides: OPENFDD_MAX_ZIP_MB, OPENFDD_MAX_UNCOMPRESSED_MB,
# OPENFDD_MAX_ENTRIES, OPENFDD_MAX_EQUIPMENT.
#
# Two-tier limits:
# - Browser Streamlit upload: BROWSER_UPLOAD_MB (500) via .streamlit/config.toml
#   maxUploadSize + optional tighter package_io check on uploaded bytes.
# - Agent / CLI / zip-from-path / folder: DEFAULT_PACKAGE_MB (2048) safety cap.
DEFAULT_PACKAGE_MB = 2048  # agent / path / CLI safety (still bounded)
BROWSER_UPLOAD_MB = 500  # Streamlit file_uploader / YouTube demos
# Real buildings: ~50 equip × (csv + columns + map) + weather + dirs ≈ 250–400 entries.
DEFAULT_MAX_ENTRIES = 2000
DEFAULT_MAX_EQUIPMENT = 100


class PackageError(ValueError):
    """User-facing package validation / extract error."""


@dataclass(frozen=True)
class PackageCaps:
    max_zip_bytes: int
    max_uncompressed_bytes: int
    max_entries: int
    max_equipment: int

    @property
    def max_zip_mb(self) -> int:
        return self.max_zip_bytes // (1024 * 1024)

    @property
    def max_uncompressed_mb(self) -> int:
        return self.max_uncompressed_bytes // (1024 * 1024)


def _env_positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return int(default)
    try:
        value = int(str(raw).strip())
    except ValueError as exc:
        raise PackageError(f"{name} must be an integer, got {raw!r}") from exc
    if value < 1:
        raise PackageError(f"{name} must be >= 1, got {value}")
    return value


def bytes_as_mb(n: int | float) -> float:
    """Round byte count to MB (binary, 1024²) for UI / reports."""
    return round(float(n) / (1024 * 1024), 6)


def directory_size_bytes(root: Path) -> int:
    """Best-effort recursive file size under root (skips unreadable files)."""
    total = 0
    try:
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            try:
                total += int(p.stat().st_size)
            except OSError:
                continue
    except OSError:
        return total
    return total


def dataset_size_caption(report: dict[str, Any] | None, *, caps: PackageCaps | None = None) -> str:
    """Human-readable size vs limit for sidebar / Overview."""
    caps = caps or effective_package_caps()
    caps_tail = (
        f"zip ≤{caps.max_zip_mb} MB · expanded ≤{caps.max_uncompressed_mb} MB · "
        f"≤{caps.max_entries} zip items (files+folders inside the archive) · "
        f"≤{caps.max_equipment} equip folders"
    )
    if not report:
        return f"Caps: {caps_tail}"
    parts: list[str] = []
    zip_mb = report.get("zip_mb")
    unc_mb = report.get("uncompressed_mb")
    if zip_mb is not None:
        parts.append(f"{zip_mb} MB zip")
    if unc_mb is not None:
        parts.append(f"{unc_mb} MB expanded")
    if not parts:
        return f"Caps: {caps_tail}"
    return (
        f"Dataset: {' · '.join(str(p) for p in parts)} "
        f"(limits {caps.max_zip_mb} / {caps.max_uncompressed_mb} MB)"
    )


def effective_package_caps(*, for_browser_upload: bool = False) -> PackageCaps:
    """Resolve zip/equipment caps from env.

    Default **2048 MB** for agent/CLI/path loads. Pass ``for_browser_upload=True``
    when ingesting Streamlit ``st.file_uploader`` bytes so validation aligns with
    ``maxUploadSize`` / ``BROWSER_UPLOAD_MB`` (500). Env overrides always win.
    """
    default_mb = BROWSER_UPLOAD_MB if for_browser_upload else DEFAULT_PACKAGE_MB
    return PackageCaps(
        max_zip_bytes=_env_positive_int("OPENFDD_MAX_ZIP_MB", default_mb) * 1024 * 1024,
        max_uncompressed_bytes=_env_positive_int("OPENFDD_MAX_UNCOMPRESSED_MB", default_mb)
        * 1024
        * 1024,
        # 200 was too tight for real buildings (~50 equip × history+columns+map+dirs).
        max_entries=_env_positive_int("OPENFDD_MAX_ENTRIES", DEFAULT_MAX_ENTRIES),
        max_equipment=_env_positive_int("OPENFDD_MAX_EQUIPMENT", DEFAULT_MAX_EQUIPMENT),
    )


class PackageManifest(BaseModel):
    schema_version: str
    building_id: str = Field(min_length=1, max_length=128)
    grid_minutes: float = Field(gt=0, le=1440)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    notes: str | None = None

    @field_validator("schema_version")
    @classmethod
    def _schema(cls, v: str) -> str:
        if v != SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {SCHEMA_VERSION!r}, got {v!r}")
        return v

    @field_validator("building_id")
    @classmethod
    def _bid(cls, v: str) -> str:
        s = v.strip()
        if not s or "/" in s or "\\" in s or s in {".", ".."}:
            raise ValueError("building_id must be a simple non-empty name")
        return s


class SessionConfig(BaseModel):
    """Optional UI restore — session_state only, never written to app disk.

    ``include_ahu_chw_valve`` is deprecated/ignored (always treated as False).
    Mech-cooling OAT bins never use AHU CHW cooling-valve %.
    """

    schema_version: str = SESSION_SCHEMA
    unit_system: str | None = None
    prefer_web_oat: bool | None = None
    chw_leave_max_f: float | None = None
    use_mech_cooling_status_proof: bool | None = True
    include_ahu_chw_valve: bool | None = False  # deprecated; apply path forces False
    role_map: dict[str, dict[str, str]] | None = None
    params: dict[str, dict[str, Any]] | None = None

    @field_validator("schema_version")
    @classmethod
    def _schema(cls, v: str) -> str:
        if v not in {SESSION_SCHEMA, "v1"}:
            raise ValueError(f"session schema_version must be {SESSION_SCHEMA!r}")
        return SESSION_SCHEMA if v == "v1" else v

    @field_validator("unit_system")
    @classmethod
    def _units(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v not in {"imperial", "metric"}:
            raise ValueError("unit_system must be imperial or metric")
        return v

    @field_validator("chw_leave_max_f")
    @classmethod
    def _leave(cls, v: float | None) -> float | None:
        if v is None:
            return v
        if not (35.0 <= float(v) <= 50.0):
            raise ValueError("chw_leave_max_f out of range (35–50 °F)")
        return float(v)


@dataclass
class PackageLoadResult:
    building_root: Path
    workdir: Path
    manifest: PackageManifest
    frames: dict[str, pd.DataFrame]
    weather: pd.DataFrame | None
    session_config: SessionConfig | None
    warnings: list[str] = field(default_factory=list)
    report: dict[str, Any] = field(default_factory=dict)
    column_map: dict[str, Any] | None = None
    column_map_issues: list[str] = field(default_factory=list)


def sweep_old_temp_dirs(*, max_age_sec: float = TEMP_MAX_AGE_SEC) -> int:
    """Best-effort cleanup of stale vibe19_* temp dirs (Cloud has no reliable session end)."""
    removed = 0
    root = Path(tempfile.gettempdir())
    now = time.time()
    for p in root.glob(f"{TEMP_PREFIX}*"):
        if not p.is_dir():
            continue
        try:
            age = now - p.stat().st_mtime
            if age > max_age_sec:
                shutil.rmtree(p, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed


def wipe_workdir(path: Path | str | None) -> None:
    if not path:
        return
    p = Path(path)
    if p.is_dir() and p.name.startswith(TEMP_PREFIX):
        shutil.rmtree(p, ignore_errors=True)


def _safe_member_path(name: str) -> Path:
    """Reject zip-slip / absolute / symlink-like paths. Return normalized relative Path."""
    raw = name.replace("\\", "/")
    if not raw or raw.endswith("/"):
        # directory entry — still validate
        parts_src = raw.rstrip("/")
    else:
        parts_src = raw
    if parts_src.startswith("/") or (len(parts_src) > 1 and parts_src[1] == ":"):
        raise PackageError(f"Absolute path in zip rejected: {name}")
    parts = [p for p in parts_src.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise PackageError(f"Path traversal rejected: {name}")
    if len(parts) > MAX_PATH_DEPTH:
        raise PackageError(f"Path too deep (>{MAX_PATH_DEPTH}): {name}")
    return Path(*parts) if parts else Path()


def _is_zip_dir(info: zipfile.ZipInfo) -> bool:
    """Directory entry detection tolerant of Windows ``Compress-Archive`` zips.

    ``ZipInfo.is_dir()`` only recognizes names ending in ``/``. PowerShell's
    ``Compress-Archive`` writes backslash separators, so its folder markers end
    in ``\\`` and would otherwise be extracted as zero-byte *files* — the real
    files inside those folders then fail with ``[Errno 20] Not a directory``.
    """
    name = info.filename
    return info.is_dir() or name.endswith(("/", "\\"))


_BACKSLASH_ZIP_HINT = (
    "This zip uses backslash path separators (typical of Windows PowerShell "
    "`Compress-Archive`). vibe19 normalizes these automatically, but if this "
    "error persists rebuild the package with forward-slash paths — e.g. Python "
    "`zipfile` / `shutil.make_archive`, 7-Zip, or the built-in Explorer "
    "'Compress to ZIP file' — and re-upload."
)


def _zip_has_backslash_paths(zf: zipfile.ZipFile) -> bool:
    # orig_filename keeps the raw stored name; Windows Python normalizes
    # ``filename`` on read, POSIX does not.
    return any(
        "\\" in getattr(i, "orig_filename", i.filename) for i in zf.infolist()
    )


def _ensure_parent_dir(target: Path, entry_name: str) -> None:
    """mkdir -p the target's parent; explain clearly if a file blocks the path."""
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except (NotADirectoryError, FileExistsError) as exc:
        raise PackageError(
            f"Cannot extract `{entry_name}`: a file is blocking the folder path "
            f"`{target.parent}`. {_BACKSLASH_ZIP_HINT}"
        ) from exc
    if target.parent.exists() and not target.parent.is_dir():
        raise PackageError(
            f"Cannot extract `{entry_name}`: `{target.parent}` exists as a file, "
            f"not a folder. {_BACKSLASH_ZIP_HINT}"
        )


def _inspect_zip(zf: zipfile.ZipFile, caps: PackageCaps | None = None) -> None:
    caps = caps or effective_package_caps()
    infos = zf.infolist()
    # Count every ZipInfo (files + directory markers). Windows Compress-Archive
    # often emits one dir entry per folder; real BUILDING_100 demos land ~250+.
    if len(infos) > caps.max_entries:
        n_files = sum(1 for i in infos if not _is_zip_dir(i))
        n_dirs = len(infos) - n_files
        raise PackageError(
            f"Zip has too many items for this upload limit "
            f"({len(infos)} items > max {caps.max_entries}). "
            f"An 'item' (zip entry) is each file or folder listed inside the zip "
            f"- not megabytes. This zip has about {n_files} file(s) and {n_dirs} folder marker(s). "
            f"Trim unused files (e.g. quality.json, fdd_*.csv, backups), or split into "
            f"smaller part-zips (see vibe19_agent_spec/docs/AGENT_CSV_PREPROCESS.md), "
            f"or raise OPENFDD_MAX_ENTRIES on the host."
        )
    total = 0
    names_lower: set[str] = set()
    for info in infos:
        if _is_zip_dir(info):
            continue
        # Symlink / special: ZipInfo flag_bits or external_attr on Unix
        if stat_is_symlink(info):
            raise PackageError(f"Symlink entries are not allowed: {info.filename}")
        if info.file_size < 0 or info.compress_size < 0:
            raise PackageError("Invalid zip entry sizes")
        # Compression bomb heuristic
        if info.compress_size > 0 and info.file_size / max(info.compress_size, 1) > 100:
            raise PackageError(f"Suspicious compression ratio: {info.filename}")
        total += int(info.file_size)
        if total > caps.max_uncompressed_bytes:
            raise PackageError(
                f"Uncompressed size exceeds {caps.max_uncompressed_mb} MB limit"
            )
        rel = _safe_member_path(info.filename)
        key = str(rel).lower()
        if key in names_lower:
            raise PackageError(f"Duplicate / case-colliding path: {info.filename}")
        names_lower.add(key)


def stat_is_symlink(info: zipfile.ZipInfo) -> bool:
    # Unix symlink: external_attr high bytes == 0o120000
    return ((info.external_attr >> 16) & 0o170000) == 0o120000


def expand_nested_zips(
    workdir: Path,
    *,
    caps: PackageCaps | None = None,
    max_depth: int = 4,
) -> list[str]:
    """Extract nested ``*.zip`` archives found under workdir (in place).

    Each nested zip is unpacked into a sibling folder named after the zip stem,
    then the zip file is removed. Weather / equipment trees may arrive nested.
    """
    caps = caps or effective_package_caps()
    notes: list[str] = []
    for _depth in range(max_depth):
        nested = sorted(p for p in workdir.rglob("*.zip") if p.is_file())
        if not nested:
            return notes
        for zpath in nested:
            try:
                rel = zpath.relative_to(workdir)
            except ValueError:
                rel = zpath
            dest = zpath.parent / zpath.stem
            dest.mkdir(parents=True, exist_ok=True)
            try:
                data = zpath.read_bytes()
                if len(data) > caps.max_zip_bytes:
                    raise PackageError(
                        f"Nested zip `{rel.as_posix()}` exceeds {caps.max_zip_mb} MB limit"
                    )
                from io import BytesIO

                with zipfile.ZipFile(BytesIO(data), "r") as zf:
                    _inspect_zip(zf, caps)
                    for info in zf.infolist():
                        if _is_zip_dir(info):
                            continue
                        member = _safe_member_path(info.filename)
                        if not member.parts:
                            continue
                        target = dest / member
                        _ensure_parent_dir(target, info.filename)
                        with zf.open(info, "r") as src, target.open("wb") as out:
                            while True:
                                chunk = src.read(1024 * 256)
                                if not chunk:
                                    break
                                out.write(chunk)
                zpath.unlink(missing_ok=True)
                notes.append(
                    f"Expanded nested zip `{rel.as_posix()}` → "
                    f"`{dest.relative_to(workdir).as_posix()}`"
                )
            except PackageError:
                raise
            except Exception as exc:
                raise PackageError(
                    f"Failed to expand nested zip `{rel.as_posix()}`: {exc}"
                ) from exc
    leftover = [p for p in workdir.rglob("*.zip") if p.is_file()]
    if leftover:
        raise PackageError(
            f"Nested zip depth exceeded ({max_depth}); "
            f"{len(leftover)} zip(s) remain unexpanded"
        )
    return notes


def extract_package_zip(
    data: bytes, *, dest: Path | None = None, caps: PackageCaps | None = None
) -> Path:
    """Extract zip bytes into a fresh temp dir. Returns workdir root."""
    caps = caps or effective_package_caps()
    if len(data) > caps.max_zip_bytes:
        raise PackageError(f"Zip exceeds {caps.max_zip_mb} MB compressed limit")
    workdir = Path(dest) if dest else Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        from io import BytesIO

        with zipfile.ZipFile(BytesIO(data), "r") as zf:
            _inspect_zip(zf, caps)
            written = 0
            for info in zf.infolist():
                if _is_zip_dir(info):
                    continue
                rel = _safe_member_path(info.filename)
                if not rel.parts:
                    continue
                target = workdir / rel
                _ensure_parent_dir(target, info.filename)
                # Stream copy with hard cap
                with zf.open(info, "r") as src, target.open("wb") as out:
                    while True:
                        chunk = src.read(1024 * 256)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > caps.max_uncompressed_bytes:
                            raise PackageError(
                                f"Uncompressed size limit exceeded during extract "
                                f"({caps.max_uncompressed_mb} MB)"
                            )
                        out.write(chunk)
        expand_nested_zips(workdir, caps=caps)
    except PackageError:
        wipe_workdir(workdir)
        raise
    except zipfile.BadZipFile as exc:
        wipe_workdir(workdir)
        raise PackageError(f"Not a valid zip file: {exc}") from exc
    except OSError as exc:
        wipe_workdir(workdir)
        hint = ""
        try:
            from io import BytesIO

            with zipfile.ZipFile(BytesIO(data), "r") as _zf:
                if _zip_has_backslash_paths(_zf):
                    hint = f" {_BACKSLASH_ZIP_HINT}"
        except Exception:
            pass
        raise PackageError(f"Zip extraction failed: {exc}.{hint}") from exc
    except Exception:
        wipe_workdir(workdir)
        raise
    return workdir


def load_package_from_dir(
    building_root: Path, *, workdir: Path | None = None, caps: PackageCaps | None = None
) -> PackageLoadResult:
    """Load a validated package directory (already extracted). Uncached."""
    manifest = load_manifest(building_root)
    session_cfg = load_session_config(building_root)
    warnings: list[str] = []

    equipment = discover_equipment(building_root)
    if not equipment:
        raise PackageError("No equipment folders with history_wide.csv found")
    caps = caps or effective_package_caps()
    if len(equipment) > caps.max_equipment:
        raise PackageError(
            f"Zip has too many equipment folders ({len(equipment)} > max {caps.max_equipment}). "
            f"Each folder with a history_wide.csv counts as one piece of equipment "
            f"(AHU, VAV box, chiller, …). Remove unused boxes or raise OPENFDD_MAX_EQUIPMENT."
        )

    ids = [e["equipment_id"] for e in equipment]
    if len(ids) != len(set(ids)):
        raise PackageError("Duplicate equipment folder names are not allowed")

    for eq in equipment:
        issues = _validate_equipment_csv(Path(eq["history_path"]))
        if issues:
            raise PackageError("; ".join(issues))

    frames: dict[str, pd.DataFrame] = {}
    for eq in equipment:
        try:
            df = load_equipment_csv(eq["history_path"], eq.get("columns_path"))
        except Exception as exc:
            raise PackageError(
                f"{eq['equipment_id']}: failed to load history_wide.csv ({exc})"
            ) from exc
        df.attrs["poll_seconds"] = float(manifest.grid_minutes) * 60.0
        df.attrs["equipment_id"] = eq["equipment_id"]
        df.attrs["building_id"] = manifest.building_id
        df.attrs["columns_path"] = str(eq["columns_path"]) if eq.get("columns_path") else None
        for issue in validate_dataframe(df):
            warnings.append(f"{eq['equipment_id']}: {issue}")
        if df.empty or not isinstance(df.index, pd.DatetimeIndex):
            raise PackageError(
                f"{eq['equipment_id']}: no usable UTC datetime index after load "
                "(need parseable timestamp_utc rows)"
            )
        frames[eq["equipment_id"]] = df

    from app.data_contract import audit_package_dir

    contract_warnings, package_health = audit_package_dir(building_root, frames, equipment)
    warnings.extend(contract_warnings)

    weather = _load_weather(building_root)
    column_map = None
    column_map_issues: list[str] = []
    root_map = None
    try:
        root_map = load_package_column_map(building_root)
    except PackageError as exc:
        warnings.append(str(exc))
        root_map = None

    from app.sidecar_maps import SidecarMapError, merge_package_column_maps

    try:
        column_map = merge_package_column_maps(
            building_root,
            equipment,
            building_id=manifest.building_id,
            root_column_map=root_map,
        )
    except SidecarMapError as exc:
        raise PackageError(str(exc)) from exc

    if column_map:
        from app.column_map_json import validate_column_map_against_frames

        column_map_issues = validate_column_map_against_frames(column_map, frames)
        if column_map_issues:
            warnings.extend(column_map_issues[:20])

    unc_bytes = directory_size_bytes(building_root)
    report = {
        "building_id": manifest.building_id,
        "schema_version": manifest.schema_version,
        "timezone": manifest.timezone,
        "grid_minutes": manifest.grid_minutes,
        "equipment_count": len(frames),
        "equipment_ids": sorted(frames),
        "has_weather": weather is not None,
        "has_session_config": session_cfg is not None,
        "has_column_map": column_map is not None,
        "column_map_equipment_count": (
            len((column_map or {}).get("equipment") or {}) if column_map else 0
        ),
        "column_map_issue_count": len(column_map_issues),
        "column_map_issues_preview": column_map_issues[:20],
        "data_contract_warning_count": len(contract_warnings),
        "data_contract_warnings_preview": contract_warnings[:30],
        "package_health": package_health.to_report_dict(),
        "package_health_grade": package_health.grade,
        "package_health_summary": list(package_health.summary_lines),
        "row_counts": {k: int(len(v)) for k, v in frames.items()},
        "uncompressed_bytes": unc_bytes,
        "uncompressed_mb": bytes_as_mb(unc_bytes),
        "max_zip_mb": caps.max_zip_mb,
        "max_uncompressed_mb": caps.max_uncompressed_mb,
        "source": "dir",
    }
    starts, ends = [], []
    for df in frames.values():
        if isinstance(df.index, pd.DatetimeIndex) and len(df):
            starts.append(df.index.min())
            ends.append(df.index.max())
    if starts:
        report["start"] = str(min(starts))
        report["end"] = str(max(ends))

    return PackageLoadResult(
        building_root=building_root,
        workdir=workdir or building_root,
        manifest=manifest,
        frames=frames,
        weather=weather,
        session_config=session_cfg,
        warnings=warnings,
        report=report,
        column_map=column_map,
        column_map_issues=column_map_issues,
    )


def _read_manifest_dict(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def manifest_is_openfdd_building(path: Path) -> bool:
    """True when ``manifest.json`` is an ``openfdd_package_v1`` building package."""
    raw = _read_manifest_dict(path)
    if not raw:
        return False
    return (
        str(raw.get("schema_version") or "") == SCHEMA_VERSION
        and bool(str(raw.get("building_id") or "").strip())
    )


def manifest_is_weather_sidecar(path: Path) -> bool:
    """True when ``manifest.json`` looks like a weather-only sidecar (not a building)."""
    raw = _read_manifest_dict(path)
    if not raw:
        return False
    if str(raw.get("schema_version") or "") == SCHEMA_VERSION and raw.get("building_id"):
        return False
    weather_keys = {"source", "output_file", "aligned_to_hvac_cleaned", "dew_point_sources"}
    return bool(
        str(raw.get("source", "")).lower().startswith("external_weather")
        or weather_keys.intersection(raw.keys())
        or ("location_id" in raw and "grid_minutes" not in raw and "building_id" not in raw)
    )


def absorb_sibling_weather(building_root: Path, workdir: Path) -> list[str]:
    """If a sibling ``weather/`` folder sits next to the building, merge or ignore it.

    Common multi-upload: ``BUILDING_*.zip`` (with nested weather) + separate ``weather.zip``.
    """
    warnings: list[str] = []
    if not workdir.is_dir() or not building_root.is_dir():
        return warnings
    try:
        sibling = (workdir / "weather").resolve()
        dest = (building_root / "weather").resolve()
    except OSError:
        return warnings
    if not sibling.is_dir():
        return warnings
    # Sibling is the building itself named weather — nothing to do
    if sibling == building_root.resolve():
        return warnings
    # Already nested under building
    if sibling == dest or dest in sibling.parents:
        return warnings
    hist = sibling / "history_wide.csv"
    if not hist.is_file():
        return warnings
    dest_hist = building_root / "weather" / "history_wide.csv"
    if dest_hist.is_file():
        warnings.append(
            "Ignored extra top-level weather/ folder — building package already includes weather/"
        )
        return warnings
    dest.mkdir(parents=True, exist_ok=True)
    for src in sibling.iterdir():
        if not src.is_file():
            continue
        target = dest / src.name
        if target.is_file():
            continue
        shutil.copy2(src, target)
    warnings.append("Merged sibling weather/ into the building package weather/ folder")
    return warnings


def resolve_building_root(workdir: Path) -> Path:
    """Find the directory that contains an openfdd building ``manifest.json``.

    Ignores weather-only sidecar manifests (e.g. a separate ``weather.zip`` extracted
    beside a ``BUILDING_*/`` folder) so multi-file uploads still resolve.
    """
    if manifest_is_openfdd_building(workdir / "manifest.json"):
        return workdir
    # Root manifest present but not openfdd — only accept if it is not weather-only
    if (workdir / "manifest.json").is_file() and not manifest_is_weather_sidecar(workdir / "manifest.json"):
        # May still validate later; keep legacy behavior for odd demos
        if discover_equipment(workdir):
            return workdir

    kids = [p for p in workdir.iterdir() if p.is_dir() and p.name.lower() != "__macosx"]
    openfdd_roots = [
        p
        for p in kids
        if p.name.lower() != "weather" and manifest_is_openfdd_building(p / "manifest.json")
    ]
    if len(openfdd_roots) == 1:
        return openfdd_roots[0]
    if len(openfdd_roots) > 1:
        names = ", ".join(p.name for p in openfdd_roots[:6])
        raise PackageError(
            f"Multiple openfdd building packages found ({names}). "
            "Upload one building zip (or split into part-zips that share a single building_id)."
        )

    # Single non-weather child with any manifest.json (legacy)
    candidates = [
        p
        for p in kids
        if p.name.lower() != "weather"
        and (p / "manifest.json").is_file()
        and not manifest_is_weather_sidecar(p / "manifest.json")
    ]
    if len(candidates) == 1:
        return candidates[0]

    # Fallback: single child that has equipment
    equip_kids = [p for p in kids if p.name.lower() != "weather" and discover_equipment(p)]
    if len(equip_kids) == 1:
        return equip_kids[0]
    if discover_equipment(workdir):
        pass
    weather_only = [
        p for p in kids if p.name.lower() == "weather" or manifest_is_weather_sidecar(p / "manifest.json")
    ]
    if weather_only and not openfdd_roots and not equip_kids:
        raise PackageError(
            "This upload looks like weather-only data, not a building package. "
            "Upload a building openfdd zip (it may already include weather/). "
            "A standalone weather.zip cannot be loaded by itself."
        )
    raise PackageError(
        "Package must contain an openfdd_package_v1 manifest.json at the zip root "
        "or inside exactly one top-level building folder. "
        "If you also selected a separate weather.zip, keep the building zip selected — "
        "weather sidecars are merged automatically when possible."
    )


def load_manifest(building_root: Path) -> PackageManifest:
    path = building_root / "manifest.json"
    if not path.is_file():
        raise PackageError("manifest.json is required")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PackageError(f"manifest.json is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise PackageError("manifest.json must be a JSON object")
    # Weather-only sidecar zips are a common mistaken upload
    weather_keys = {"source", "output_file", "aligned_to_hvac_cleaned", "dew_point_sources"}
    looks_weather = (
        "schema_version" not in raw
        and "building_id" not in raw
        and (
            str(raw.get("source", "")).lower().startswith("external_weather")
            or weather_keys.intersection(raw.keys())
            or (
                "location_id" in raw
                and "grid_minutes" not in raw
                and not discover_equipment(building_root)
            )
        )
    )
    if looks_weather:
        raise PackageError(
            "This zip looks like weather-only data, not a building package. "
            "Upload a building openfdd zip (it should already include a weather/ folder). "
            "A standalone weather.zip cannot be loaded by itself - "
            "manifest.json must be openfdd_package_v1 with building_id + grid_minutes."
        )
    try:
        return PackageManifest.model_validate(raw)
    except Exception as exc:  # pydantic ValidationError
        raise PackageError(
            "manifest.json is not a valid openfdd_package_v1 building manifest. "
            f"Need schema_version={SCHEMA_VERSION!r}, building_id, and grid_minutes. "
            f"Details: {exc}"
        ) from exc


def load_session_config(building_root: Path) -> SessionConfig | None:
    path = building_root / "session_config.json"
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return SessionConfig.model_validate(raw)
    except Exception as exc:
        raise PackageError(f"session_config.json invalid: {exc}") from exc


def load_package_column_map(building_root: Path) -> dict[str, Any] | None:
    """Load optional package-root ``column_map.json`` (Haystack-like or flat)."""
    path = building_root / "column_map.json"
    if not path.is_file():
        return None
    try:
        from app.column_map_json import load_column_map_json

        return load_column_map_json(path)
    except Exception as exc:
        raise PackageError(f"column_map.json invalid: {exc}") from exc


def _load_weather(building_root: Path) -> pd.DataFrame | None:
    hist = building_root / "weather" / "history_wide.csv"
    if not hist.is_file():
        return None
    cols = building_root / "weather" / "columns.csv"
    try:
        df = load_equipment_csv(hist, cols if cols.is_file() else None)
        from app.weather_psychrometrics import enrich_weather_frame

        return enrich_weather_frame(df)
    except Exception:
        # Bad weather sidecar must not fail the whole package load
        return None


def _validate_equipment_csv(path: Path) -> list[str]:
    issues: list[str] = []
    # Header-only read first
    try:
        header = pd.read_csv(path, nrows=0)
    except Exception as exc:
        return [f"{path.name}: cannot read CSV ({exc})"]
    cols = list(header.columns)
    if len(cols) > MAX_COLUMNS:
        issues.append(f"{path.parent.name}: too many columns ({len(cols)} > {MAX_COLUMNS})")
    if "timestamp_utc" not in cols:
        issues.append(f"{path.parent.name}: missing required column timestamp_utc")
        return issues
    # Sample first rows for parseability
    try:
        sample = pd.read_csv(path, nrows=5, usecols=["timestamp_utc"])
        ts = pd.to_datetime(sample["timestamp_utc"], utc=True, errors="coerce")
        if ts.isna().all():
            issues.append(f"{path.parent.name}: timestamp_utc did not parse as datetime")
    except Exception as exc:
        issues.append(f"{path.parent.name}: timestamp check failed ({exc})")
    return issues



def load_package_zip(data: bytes, *, caps: PackageCaps | None = None) -> PackageLoadResult:
    """Extract + validate + load. Caller owns wipe via result.workdir.

    Pass ``caps=effective_package_caps(for_browser_upload=True)`` for Streamlit
    uploader bytes (500 MB). Agent/CLI/path use default 2048 MB caps.
    """
    sweep_old_temp_dirs()
    caps = caps or effective_package_caps()
    workdir = extract_package_zip(data, caps=caps)
    try:
        building_root = resolve_building_root(workdir)
        result = load_package_from_dir(building_root, workdir=workdir, caps=caps)
        result.report["source"] = "zip"
        result.report["zip_bytes"] = len(data)
        result.report["zip_mb"] = bytes_as_mb(len(data))
        return result
    except Exception:
        wipe_workdir(workdir)
        raise


def apply_session_config(cfg: SessionConfig, *, equipment_ids: set[str]) -> list[str]:
    """Apply optional session_config into streamlit session_state. Returns warnings."""
    import streamlit as st

    warnings: list[str] = []
    if cfg.unit_system is not None:
        st.session_state.unit_system = cfg.unit_system
    if cfg.prefer_web_oat is not None:
        st.session_state.prefer_web_oat = bool(cfg.prefer_web_oat)
    if cfg.chw_leave_max_f is not None:
        st.session_state.chw_leave_max_f = float(cfg.chw_leave_max_f)
        # Resync unit-aware display slider on next render
        st.session_state.pop("_chw_leave_max_f_ui_unit", None)
    if cfg.use_mech_cooling_status_proof is not None:
        st.session_state.use_mech_cooling_status_proof = bool(
            cfg.use_mech_cooling_status_proof
        )
    # Legacy session configs may still carry this key; never enable valve→mech-cooling bins.
    st.session_state.include_ahu_chw_valve = False
    if cfg.include_ahu_chw_valve:
        warnings.append(
            "session_config include_ahu_chw_valve ignored — mech-cooling OAT bins are compressor/chiller/DX only (not valves or pump-alone)"
        )
    st.session_state.apply_occupancy_calendar = True
    if cfg.params:
        params = dict(st.session_state.get("params") or {})
        for rid, p in cfg.params.items():
            if isinstance(p, dict):
                params[rid] = {**params.get(rid, {}), **p}
        st.session_state.params = params
    if cfg.role_map:
        role_map = dict(st.session_state.get("role_map") or {})
        for eq_id, roles in cfg.role_map.items():
            if eq_id not in equipment_ids:
                warnings.append(f"session_config role_map: unknown equipment {eq_id}")
                continue
            if not isinstance(roles, dict):
                continue
            cleaned = {str(r): str(c) for r, c in roles.items() if r and c}
            role_map[eq_id] = {**role_map.get(eq_id, {}), **cleaned}
        st.session_state.role_map = role_map
        frames = st.session_state.get("equipment_frames") or {}
        if frames:
            from app.site_model import stamp_equipment_type

            for eq_id, df in frames.items():
                stamp_equipment_type(df, eq_id, role_map=role_map)
                pg = (role_map.get(eq_id) or {}).get("plant_group")
                if pg:
                    df.attrs["plant_group"] = str(pg)
    return warnings
