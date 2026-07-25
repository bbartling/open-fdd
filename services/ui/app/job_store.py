"""Persistent analysis Job store under ``workspace/jobs/<job_id>/``.

Filesystem contract for Open-FDD engineering Jobs (migration PR1).
Telemetry stays in Feather/parquet; this store holds metadata, mapping,
configs, and run/findings directories — never SQLite historian tables.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1
_JOB_ID_RE = re.compile(r"^job-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
_SUBDIRS = (
    "mapping",
    "configs",
    "runs",
    "findings",
    "reports",
    "wattlab",
    "artifacts",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def workspace_root(explicit: str | Path | None = None) -> Path:
    """Resolve site workspace root (bind-mounted ``workspace/`` in containers)."""
    if explicit is not None:
        return Path(explicit).expanduser().resolve()
    env = os.environ.get("OPENFDD_WORKSPACE") or os.environ.get("OPENFDD_WORKSPACE_DIR")
    if env:
        return Path(env).expanduser().resolve()
    # Common local / compose defaults
    for candidate in (Path("workspace"), Path("/workspace"), Path.cwd() / "workspace"):
        if candidate.is_dir():
            return candidate.resolve()
    return (Path.cwd() / "workspace").resolve()


def jobs_root(ws: Path | None = None) -> Path:
    root = (ws or workspace_root()) / "jobs"
    root.mkdir(parents=True, exist_ok=True)
    return root


@dataclass
class JobRevisions:
    dataset: str | None = None
    mapping: str | None = None
    config: str | None = None
    engine: str | None = None

    @classmethod
    def from_dict(cls, raw: Any) -> JobRevisions:
        if not isinstance(raw, dict):
            return cls()
        return cls(
            dataset=raw.get("dataset"),
            mapping=raw.get("mapping"),
            config=raw.get("config"),
            engine=raw.get("engine"),
        )


@dataclass
class JobMeta:
    schema_version: int
    job_id: str
    job_name: str
    site_name: str | None = None
    building_name: str | None = None
    description: str | None = None
    status: str = "active"  # active | archived
    created_at: str = ""
    updated_at: str = ""
    tags: list[str] = field(default_factory=list)
    revisions: JobRevisions = field(default_factory=JobRevisions)
    mapping_path: str | None = None  # relative to job dir when set

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> JobMeta:
        if not isinstance(raw, dict):
            raise ValueError("job.json must be an object")
        job_id = raw.get("job_id")
        if not isinstance(job_id, str) or not _JOB_ID_RE.match(job_id):
            raise ValueError(f"invalid job_id: {job_id!r}")
        name = raw.get("job_name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("job_name is required")
        ver = raw.get("schema_version", SCHEMA_VERSION)
        if ver != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version: {ver}")
        status = raw.get("status") or "active"
        if status not in ("active", "archived"):
            raise ValueError(f"invalid status: {status!r}")
        tags = raw.get("tags") or []
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            raise ValueError("tags must be a list of strings")
        return cls(
            schema_version=int(ver),
            job_id=job_id,
            job_name=name.strip(),
            site_name=raw.get("site_name"),
            building_name=raw.get("building_name"),
            description=raw.get("description"),
            status=status,
            created_at=str(raw.get("created_at") or ""),
            updated_at=str(raw.get("updated_at") or ""),
            tags=list(tags),
            revisions=JobRevisions.from_dict(raw.get("revisions")),
            mapping_path=raw.get("mapping_path"),
        )


def new_job_id() -> str:
    return f"job-{uuid.uuid4()}"


def job_dir(job_id: str, ws: Path | None = None) -> Path:
    if not _JOB_ID_RE.match(job_id):
        raise ValueError(f"invalid job_id: {job_id!r}")
    return jobs_root(ws) / job_id


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=".job-", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _ensure_layout(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for name in _SUBDIRS:
        (path / name).mkdir(parents=True, exist_ok=True)


def create_job(
    job_name: str,
    *,
    site_name: str | None = None,
    building_name: str | None = None,
    description: str | None = None,
    tags: Iterable[str] | None = None,
    ws: Path | None = None,
) -> JobMeta:
    now = _utc_now()
    meta = JobMeta(
        schema_version=SCHEMA_VERSION,
        job_id=new_job_id(),
        job_name=job_name.strip(),
        site_name=site_name,
        building_name=building_name,
        description=description,
        status="active",
        created_at=now,
        updated_at=now,
        tags=list(tags or []),
    )
    if not meta.job_name:
        raise ValueError("job_name is required")
    path = job_dir(meta.job_id, ws)
    if path.exists():
        raise RuntimeError(f"job directory already exists: {path}")
    _ensure_layout(path)
    _atomic_write_json(path / "job.json", meta.to_dict())
    return meta


def save_job(meta: JobMeta, *, ws: Path | None = None) -> JobMeta:
    """Persist metadata (updates ``updated_at``)."""
    meta = JobMeta.from_dict(meta.to_dict())  # validate
    meta.updated_at = _utc_now()
    path = job_dir(meta.job_id, ws)
    if not path.is_dir():
        raise FileNotFoundError(f"job not found: {meta.job_id}")
    _ensure_layout(path)
    _atomic_write_json(path / "job.json", meta.to_dict())
    return meta


def load_job(job_id: str, *, ws: Path | None = None) -> JobMeta:
    path = job_dir(job_id, ws) / "job.json"
    if not path.is_file():
        raise FileNotFoundError(f"job not found: {job_id}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"malformed job.json for {job_id}: {exc}") from exc
    return JobMeta.from_dict(raw)


def list_jobs(*, ws: Path | None = None, include_archived: bool = True) -> list[JobMeta]:
    root = jobs_root(ws)
    out: list[JobMeta] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or not child.name.startswith("job-"):
            continue
        meta_path = child / "job.json"
        if not meta_path.is_file():
            continue
        try:
            meta = load_job(child.name, ws=ws)
        except (ValueError, FileNotFoundError, OSError):
            continue
        if not include_archived and meta.status == "archived":
            continue
        out.append(meta)
    out.sort(key=lambda m: m.updated_at or m.created_at, reverse=True)
    return out


def archive_job(job_id: str, *, ws: Path | None = None) -> JobMeta:
    meta = load_job(job_id, ws=ws)
    meta.status = "archived"
    return save_job(meta, ws=ws)


def rename_job(job_id: str, job_name: str, *, ws: Path | None = None) -> JobMeta:
    meta = load_job(job_id, ws=ws)
    meta.job_name = job_name.strip()
    if not meta.job_name:
        raise ValueError("job_name is required")
    return save_job(meta, ws=ws)


def save_mapping(
    job_id: str,
    mapping: dict[str, Any],
    *,
    mapping_revision: str | None = None,
    ws: Path | None = None,
) -> JobMeta:
    """Write ``mapping/role_map.json`` and stamp mapping revision."""
    meta = load_job(job_id, ws=ws)
    path = job_dir(job_id, ws)
    rel = "mapping/role_map.json"
    _atomic_write_json(path / rel, mapping)
    meta.mapping_path = rel
    rev = mapping_revision or _utc_now()
    meta.revisions.mapping = rev
    return save_job(meta, ws=ws)


def load_mapping(job_id: str, *, ws: Path | None = None) -> dict[str, Any] | None:
    meta = load_job(job_id, ws=ws)
    if not meta.mapping_path:
        return None
    path = job_dir(job_id, ws) / meta.mapping_path
    if not path.is_file():
        raise FileNotFoundError(f"mapping missing for {job_id}: {meta.mapping_path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("mapping must be a JSON object")
    return raw


def delete_job(job_id: str, *, ws: Path | None = None, confirm: bool = False) -> None:
    if not confirm:
        raise ValueError("delete_job requires confirm=True")
    path = job_dir(job_id, ws)
    if not path.is_dir():
        raise FileNotFoundError(f"job not found: {job_id}")
    # Safety: only delete under jobs_root
    root = jobs_root(ws).resolve()
    resolved = path.resolve()
    if root not in resolved.parents and resolved != root:
        raise RuntimeError("refusing to delete path outside jobs root")
    import shutil

    shutil.rmtree(resolved)
