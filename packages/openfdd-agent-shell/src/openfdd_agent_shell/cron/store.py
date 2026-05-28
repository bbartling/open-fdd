from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..manifest import Manifest
from .models import CronJob, CronRunResult


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def format_timestamp(dt: datetime) -> str:
    return _iso(dt)


@dataclass
class CronStore:
    jobs_file: Path
    state_file: Path
    runs_dir: Path

    @classmethod
    def from_manifest(cls, manifest: Manifest) -> CronStore:
        cfg = manifest.cron
        return cls(
            jobs_file=cfg.jobs_file,
            state_file=cfg.state_file,
            runs_dir=cfg.runs_dir,
        )

    def ensure_layout(self) -> None:
        self.jobs_file.parent.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        if not self.jobs_file.is_file():
            payload = {"version": 1, "jobs": []}
            self.jobs_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        if not self.state_file.is_file():
            self.state_file.write_text(
                json.dumps({"version": 1, "jobs": {}}, indent=2),
                encoding="utf-8",
            )

    def load_jobs(self) -> list[CronJob]:
        self.ensure_layout()
        data = json.loads(self.jobs_file.read_text(encoding="utf-8"))
        return [CronJob.from_dict(item) for item in data.get("jobs", [])]

    def save_jobs(self, jobs: list[CronJob]) -> None:
        self.jobs_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "jobs": [job.to_dict() for job in jobs]}
        self.jobs_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def load_state(self) -> dict[str, Any]:
        self.ensure_layout()
        return json.loads(self.state_file.read_text(encoding="utf-8"))

    def save_state(self, state: dict[str, Any]) -> None:
        self.ensure_layout()
        self.state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def job_state(self, job_id: str) -> dict[str, Any]:
        state = self.load_state()
        jobs = state.setdefault("jobs", {})
        return jobs.setdefault(job_id, {})

    def update_job_state(self, job_id: str, **fields: Any) -> None:
        state = self.load_state()
        jobs = state.setdefault("jobs", {})
        entry = jobs.setdefault(job_id, {})
        entry.update(fields)
        self.save_state(state)

    def add_job(self, job: CronJob) -> CronJob:
        jobs = self.load_jobs()
        jobs.append(job)
        self.save_jobs(jobs)
        return job

    def remove_job(self, job_id: str) -> bool:
        jobs = self.load_jobs()
        new_jobs = [job for job in jobs if job.id != job_id]
        if len(new_jobs) == len(jobs):
            return False
        self.save_jobs(new_jobs)
        return True

    def get_job(self, job_id: str) -> CronJob | None:
        for job in self.load_jobs():
            if job.id == job_id:
                return job
        return None

    def write_run(self, result: CronRunResult) -> Path:
        job_dir = self.runs_dir / result.job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        path = job_dir / f"{result.run_id}.json"
        path.write_text(
            json.dumps(
                {
                    "job_id": result.job_id,
                    "run_id": result.run_id,
                    "status": result.status,
                    "message": result.message,
                    "started_at": result.started_at,
                    "finished_at": result.finished_at,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return path

    def new_run_id(self) -> str:
        return uuid.uuid4().hex

    @staticmethod
    def timestamp() -> str:
        return _iso(_utc_now())
