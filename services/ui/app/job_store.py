"""Persistent analysis Job store under ``workspace/jobs/<job_id>/``.

Filesystem contract for Open-FDD engineering Jobs (Milestone B1).
Telemetry stays in Feather/parquet; this store holds metadata, mapping,
configs, dataset refs, and run/findings directories — never SQLite historian tables.

Streamlit ``st.session_state`` is **not** the source of truth.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1
_JOB_ID_RE = re.compile(r"^job-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
_RUN_ID_RE = re.compile(r"^run-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
_SUBDIRS = (
    "mapping",
    "configs",
    "datasets",
    "runs",
    "findings",
    "reports",
    "wattlab",
    "artifacts",
)


class RevisionConflict(Exception):
    """Stale write — client meta_revision does not match on-disk value."""

    def __init__(self, expected: str, current: str) -> None:
        self.expected = expected
        self.current = current
        super().__init__(
            f"revision_conflict expected={expected!r} current={current!r}"
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
    created_by: str | None = None
    site_id: str | None = None
    tags: list[str] = field(default_factory=list)
    revisions: JobRevisions = field(default_factory=JobRevisions)
    mapping_path: str | None = None
    latest_run_id: str | None = None
    latest_findings_revision: str | None = None
    meta_revision: str = ""
    archived: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> JobMeta:
        if not isinstance(raw, dict):
            raise ValueError("job.json must be an object")
        job_id = raw.get("job_id")
        if not isinstance(job_id, str) or not _JOB_ID_RE.match(job_id):
            raise ValueError(f"invalid job_id: {job_id!r}")
        name = raw.get("job_name") or raw.get("name")
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
        latest_run = raw.get("latest_run_id")
        if latest_run is not None and (
            not isinstance(latest_run, str) or not _RUN_ID_RE.match(latest_run)
        ):
            raise ValueError(f"invalid latest_run_id: {latest_run!r}")
        archived = bool(raw.get("archived", status == "archived"))
        if status == "archived":
            archived = True
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
            created_by=raw.get("created_by"),
            site_id=raw.get("site_id"),
            tags=list(tags),
            revisions=JobRevisions.from_dict(raw.get("revisions")),
            mapping_path=raw.get("mapping_path"),
            latest_run_id=latest_run,
            latest_findings_revision=raw.get("latest_findings_revision"),
            meta_revision=str(raw.get("meta_revision") or ""),
            archived=archived,
        )


def new_job_id() -> str:
    return f"job-{uuid.uuid4()}"


def new_run_id() -> str:
    return f"run-{uuid.uuid4()}"


def new_meta_revision() -> str:
    return uuid.uuid4().hex


def job_dir(job_id: str, ws: Path | None = None) -> Path:
    if not _JOB_ID_RE.match(job_id):
        raise ValueError(f"invalid job_id: {job_id!r}")
    root = jobs_root(ws).resolve()
    path = (root / job_id).resolve()
    if root not in path.parents and path != root:
        raise ValueError("path traversal rejected for job_id")
    return path


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
    # Nested wattlab handoffs
    (path / "wattlab" / "handoffs").mkdir(parents=True, exist_ok=True)
    (path / "wattlab" / "runs").mkdir(parents=True, exist_ok=True)


def create_job(
    job_name: str,
    *,
    site_name: str | None = None,
    building_name: str | None = None,
    description: str | None = None,
    tags: Iterable[str] | None = None,
    created_by: str | None = None,
    site_id: str | None = None,
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
        created_by=created_by,
        site_id=site_id,
        tags=list(tags or []),
        meta_revision=new_meta_revision(),
        archived=False,
    )
    if not meta.job_name:
        raise ValueError("job_name is required")
    path = job_dir(meta.job_id, ws)
    if path.exists():
        raise RuntimeError(f"job directory already exists: {path}")
    _ensure_layout(path)
    _atomic_write_json(path / "job.json", meta.to_dict())
    _atomic_write_json(
        path / "datasets" / "dataset_refs.json",
        {"schema_version": "1", "datasets": []},
    )
    return meta


def save_job(
    meta: JobMeta,
    *,
    ws: Path | None = None,
    expected_meta_revision: str | None = None,
) -> JobMeta:
    """Persist metadata (updates ``updated_at`` and bumps ``meta_revision``)."""
    meta = JobMeta.from_dict(meta.to_dict())
    path = job_dir(meta.job_id, ws)
    if not path.is_dir():
        raise FileNotFoundError(f"job not found: {meta.job_id}")
    on_disk = load_job(meta.job_id, ws=ws)
    if expected_meta_revision is not None:
        if on_disk.meta_revision != expected_meta_revision:
            raise RevisionConflict(expected_meta_revision, on_disk.meta_revision)
    elif meta.meta_revision and on_disk.meta_revision and meta.meta_revision != on_disk.meta_revision:
        # Caller passed stale meta_revision in the object without expected= kw
        raise RevisionConflict(meta.meta_revision, on_disk.meta_revision)

    meta.updated_at = _utc_now()
    meta.meta_revision = new_meta_revision()
    if meta.status == "archived":
        meta.archived = True
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


def list_jobs(
    *,
    ws: Path | None = None,
    include_archived: bool = True,
    status: str | None = None,
    site_id: str | None = None,
    tag: str | None = None,
) -> list[JobMeta]:
    """List jobs from metadata only (skips corrupt job.json entries)."""
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
        if status == "active" and meta.status != "active":
            continue
        if status == "archived" and meta.status != "archived":
            continue
        if not include_archived and meta.status == "archived":
            continue
        if site_id is not None and meta.site_id != site_id:
            continue
        if tag is not None and tag not in meta.tags:
            continue
        out.append(meta)
    out.sort(key=lambda m: m.updated_at or m.created_at, reverse=True)
    return out


def archive_job(job_id: str, *, ws: Path | None = None) -> JobMeta:
    meta = load_job(job_id, ws=ws)
    expected = meta.meta_revision
    meta.status = "archived"
    meta.archived = True
    return save_job(meta, ws=ws, expected_meta_revision=expected)


def restore_job(job_id: str, *, ws: Path | None = None) -> JobMeta:
    meta = load_job(job_id, ws=ws)
    expected = meta.meta_revision
    meta.status = "active"
    meta.archived = False
    return save_job(meta, ws=ws, expected_meta_revision=expected)


def rename_job(job_id: str, job_name: str, *, ws: Path | None = None) -> JobMeta:
    meta = load_job(job_id, ws=ws)
    expected = meta.meta_revision
    meta.job_name = job_name.strip()
    if not meta.job_name:
        raise ValueError("job_name is required")
    return save_job(meta, ws=ws, expected_meta_revision=expected)


def duplicate_job(job_id: str, *, new_name: str | None = None, ws: Path | None = None) -> JobMeta:
    """Copy metadata + mapping/config/dataset_refs; do not copy runs/findings/reports."""
    src = load_job(job_id, ws=ws)
    src_dir = job_dir(job_id, ws)
    copy = create_job(
        new_name or f"{src.job_name} (copy)",
        site_name=src.site_name,
        building_name=src.building_name,
        description=src.description,
        tags=src.tags,
        created_by=src.created_by,
        site_id=src.site_id,
        ws=ws,
    )
    dst_dir = job_dir(copy.job_id, ws)
    for rel in (
        "mapping/role_map.json",
        "mapping/equipment_map.json",
        "configs/session_config.json",
        "configs/rule_parameters.json",
        "configs/schedules.json",
        "datasets/dataset_refs.json",
    ):
        src_path = src_dir / rel
        if src_path.is_file():
            dst = dst_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dst)
    copy = load_job(copy.job_id, ws=ws)
    expected = copy.meta_revision
    if (dst_dir / "mapping" / "role_map.json").is_file():
        copy.mapping_path = "mapping/role_map.json"
        copy.revisions.mapping = src.revisions.mapping
    copy.revisions.dataset = src.revisions.dataset
    copy.revisions.config = src.revisions.config
    return save_job(copy, ws=ws, expected_meta_revision=expected)


def save_mapping(
    job_id: str,
    mapping: dict[str, Any],
    *,
    mapping_revision: str | None = None,
    ws: Path | None = None,
) -> JobMeta:
    meta = load_job(job_id, ws=ws)
    expected = meta.meta_revision
    path = job_dir(job_id, ws)
    rel = "mapping/role_map.json"
    _atomic_write_json(path / rel, mapping)
    meta.mapping_path = rel
    meta.revisions.mapping = mapping_revision or _utc_now()
    return save_job(meta, ws=ws, expected_meta_revision=expected)


def load_mapping(job_id: str, *, ws: Path | None = None) -> dict[str, Any] | None:
    meta = load_job(job_id, ws=ws)
    if not meta.mapping_path:
        return None
    path = job_dir(job_id, ws) / meta.mapping_path
    # Containment
    job_root = job_dir(job_id, ws).resolve()
    resolved = path.resolve()
    if job_root not in resolved.parents and resolved != job_root:
        raise ValueError("mapping path escapes job directory")
    if not path.is_file():
        raise FileNotFoundError(f"mapping missing for {job_id}: {meta.mapping_path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("mapping must be a JSON object")
    return raw


def save_dataset_refs(
    job_id: str,
    refs: dict[str, Any],
    *,
    dataset_revision: str | None = None,
    ws: Path | None = None,
) -> JobMeta:
    if not isinstance(refs, dict) or refs.get("schema_version") is None:
        raise ValueError("dataset_refs must be an object with schema_version")
    meta = load_job(job_id, ws=ws)
    expected = meta.meta_revision
    path = job_dir(job_id, ws) / "datasets" / "dataset_refs.json"
    _atomic_write_json(path, refs)
    meta.revisions.dataset = dataset_revision or _utc_now()
    return save_job(meta, ws=ws, expected_meta_revision=expected)


def load_dataset_refs(job_id: str, *, ws: Path | None = None) -> dict[str, Any]:
    path = job_dir(job_id, ws) / "datasets" / "dataset_refs.json"
    if not path.is_file():
        return {"schema_version": "1", "datasets": []}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("dataset_refs must be a JSON object")
    return raw


def delete_job(job_id: str, *, ws: Path | None = None, confirm: bool = False) -> None:
    if not confirm:
        raise ValueError("delete_job requires confirm=True")
    path = job_dir(job_id, ws)
    if not path.is_dir():
        raise FileNotFoundError(f"job not found: {job_id}")
    root = jobs_root(ws).resolve()
    resolved = path.resolve()
    if root not in resolved.parents and resolved != root:
        raise RuntimeError("refusing to delete path outside jobs root")
    shutil.rmtree(resolved)


def save_findings(
    job_id: str,
    findings: dict[str, Any],
    *,
    findings_revision: str | None = None,
    ws: Path | None = None,
) -> JobMeta:
    if not isinstance(findings, dict) or findings.get("schema_version") is None:
        raise ValueError("findings must be an object with schema_version")
    meta = load_job(job_id, ws=ws)
    expected = meta.meta_revision
    path = job_dir(job_id, ws) / "findings" / "findings.json"
    _atomic_write_json(path, findings)
    meta.latest_findings_revision = findings_revision or _utc_now()
    return save_job(meta, ws=ws, expected_meta_revision=expected)


def load_findings(job_id: str, *, ws: Path | None = None) -> dict[str, Any]:
    path = job_dir(job_id, ws) / "findings" / "findings.json"
    if not path.is_file():
        return {"schema_version": "1", "findings": []}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("findings must be a JSON object")
    return raw


def save_dispositions(
    job_id: str,
    dispositions: dict[str, Any],
    *,
    ws: Path | None = None,
) -> None:
    if not isinstance(dispositions, dict) or dispositions.get("schema_version") is None:
        raise ValueError("dispositions must be an object with schema_version")
    items = dispositions.get("dispositions")
    if items is not None:
        if not isinstance(items, list):
            raise ValueError("dispositions.dispositions must be an array")
        for row in items:
            if not isinstance(row, dict) or not row.get("correlation_key"):
                raise ValueError("each disposition must include correlation_key")
    _ = load_job(job_id, ws=ws)
    path = job_dir(job_id, ws) / "findings" / "dispositions.json"
    _atomic_write_json(path, dispositions)


def load_dispositions(job_id: str, *, ws: Path | None = None) -> dict[str, Any]:
    path = job_dir(job_id, ws) / "findings" / "dispositions.json"
    if not path.is_file():
        return {"schema_version": "1", "dispositions": []}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("dispositions must be a JSON object")
    return raw


def save_wattlab_handoff(
    job_id: str,
    handoff: dict[str, Any],
    *,
    handoff_id: str | None = None,
    ws: Path | None = None,
) -> Path:
    """Write job-native WattLab handoff manifest (B8). Does not duplicate telemetry."""
    if not isinstance(handoff, dict):
        raise ValueError("handoff must be an object")
    hid = handoff_id or f"handoff-{uuid.uuid4()}"
    meta = load_job(job_id, ws=ws)
    payload = {
        "schema_version": "1",
        "handoff_id": hid,
        "job_id": job_id,
        "run_id": handoff.get("run_id") or meta.latest_run_id,
        "findings_revision": handoff.get("findings_revision") or meta.latest_findings_revision,
        "created_at": _utc_now(),
        **{k: v for k, v in handoff.items() if k not in {"schema_version", "handoff_id", "job_id"}},
    }
    path = job_dir(job_id, ws) / "wattlab" / "handoffs" / f"{hid}.json"
    _atomic_write_json(path, payload)
    return path


def save_ecm_request(
    job_id: str,
    request: dict[str, Any],
    *,
    request_id: str | None = None,
    ws: Path | None = None,
) -> Path:
    """Write an ECM package (agent-build) request under ``wattlab/ecm/`` (OFDD-076).

    Central stays free of ECM/IDF logic; this is a job-native placeholder request
    that the WattLab / open_fdd.ecm_engineering agent-build path consumes. Does not
    duplicate telemetry.
    """
    if not isinstance(request, dict):
        raise ValueError("ecm request must be an object")
    rid = request_id or f"ecm-{uuid.uuid4()}"
    if "/" in rid or "\\" in rid or ".." in rid:
        raise ValueError("invalid ecm request id")
    meta = load_job(job_id, ws=ws)
    payload = {
        "schema_version": "1",
        "kind": "ecm_package_request",
        "request_id": rid,
        "job_id": job_id,
        "run_id": request.get("run_id") or meta.latest_run_id,
        "created_at": _utc_now(),
        **{k: v for k, v in request.items() if k not in {"schema_version", "kind", "request_id", "job_id"}},
    }
    path = job_dir(job_id, ws) / "wattlab" / "ecm" / f"{rid}.json"
    _atomic_write_json(path, payload)
    return path
