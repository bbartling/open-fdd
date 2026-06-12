"""Persist Central validation job cycles (JSON, no secrets)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _jobs_dir(data_dir: Path | None = None) -> Path:
    root = data_dir or (Path(__file__).resolve().parents[1] / "data")
    path = root / "validation_jobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_job(
    *,
    site_id: str,
    plan: str,
    interval_hours: float = 0,
    duration_hours: float = 0,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id,
        "site_id": site_id,
        "plan": plan,
        "interval_hours": interval_hours,
        "duration_hours": duration_hours,
        "status": "pending",
        "created_at": _now(),
        "updated_at": _now(),
        "cycles": [],
        "summary": {"ok_cycles": 0, "total_cycles": 0},
    }
    path = _jobs_dir(data_dir) / f"{job_id}.json"
    path.write_text(json.dumps(job, indent=2), encoding="utf-8")
    return job


def load_job(job_id: str, *, data_dir: Path | None = None) -> dict[str, Any]:
    path = _jobs_dir(data_dir) / f"{job_id}.json"
    if not path.is_file():
        raise FileNotFoundError(job_id)
    return json.loads(path.read_text(encoding="utf-8"))


def save_job(job: dict[str, Any], *, data_dir: Path | None = None) -> None:
    job_id = str(job.get("id") or "")
    if not job_id:
        raise ValueError("job missing id")
    job["updated_at"] = _now()
    path = _jobs_dir(data_dir) / f"{job_id}.json"
    path.write_text(json.dumps(job, indent=2), encoding="utf-8")


def list_jobs(*, data_dir: Path | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in sorted(_jobs_dir(data_dir).glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(job, dict):
                out.append(job)
        except json.JSONDecodeError:
            continue
    return out


def append_cycle(job_id: str, cycle: dict[str, Any], *, data_dir: Path | None = None) -> dict[str, Any]:
    job = load_job(job_id, data_dir=data_dir)
    cycles = job.setdefault("cycles", [])
    if not isinstance(cycles, list):
        cycles = []
        job["cycles"] = cycles
    cycles.append(cycle)
    ok = sum(1 for c in cycles if c.get("ok"))
    job["summary"] = {"ok_cycles": ok, "total_cycles": len(cycles)}
    job["status"] = "completed" if cycle.get("final") else "running"
    save_job(job, data_dir=data_dir)
    return job
