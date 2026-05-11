from __future__ import annotations

from datetime import datetime, timedelta, timezone
import subprocess
from typing import Any

from ..manifest import Manifest
from ..memory.store import MemoryStore
from .models import CronJob, CronRunResult, Schedule
from .store import CronStore, format_timestamp


def _parse_at(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def _next_run(schedule: Schedule, after: datetime) -> datetime | None:
    if schedule.kind == "at":
        if not schedule.at_iso:
            return None
        target = _parse_at(schedule.at_iso)
        return target if target > after else None
    if schedule.kind == "every":
        seconds = int(schedule.every_seconds or 60)
        return after + timedelta(seconds=seconds)
    if schedule.kind == "cron":
        try:
            from croniter import croniter
        except ImportError as exc:
            raise RuntimeError("cron schedules require the croniter package") from exc
        base = after.astimezone(timezone.utc)
        iterator = croniter(schedule.cron_expr, base)
        nxt = iterator.get_next(datetime)
        if nxt.tzinfo is None:
            nxt = nxt.replace(tzinfo=timezone.utc)
        return nxt.astimezone(timezone.utc)
    return None


class CronScheduler:
    def __init__(self, manifest: Manifest) -> None:
        self.manifest = manifest
        self.store = CronStore.from_manifest(manifest)
        self.memory = MemoryStore(manifest)

    def due_jobs(self, now: datetime | None = None) -> list[CronJob]:
        now = now or datetime.now(timezone.utc)
        due: list[CronJob] = []
        for job in self.store.load_jobs():
            if not job.enabled:
                continue
            state = self.store.job_state(job.id)
            next_raw = state.get("next_run_at")
            if next_raw:
                next_at = _parse_at(str(next_raw))
            else:
                next_at = _next_run(job.schedule, now - timedelta(seconds=1))
                if next_at is not None:
                    self.store.update_job_state(
                        job.id, next_run_at=format_timestamp(next_at)
                    )
            if next_at is not None and next_at <= now:
                due.append(job)
        return due

    def run_job(self, job: CronJob, *, dry_run: bool = False) -> CronRunResult:
        started = CronStore.timestamp()
        run_id = self.store.new_run_id()
        if dry_run:
            result = CronRunResult(
                job_id=job.id,
                run_id=run_id,
                status="skipped",
                message=f"dry-run {job.service}",
                started_at=started,
                finished_at=CronStore.timestamp(),
            )
            self.store.write_run(result)
            return result
        try:
            message = self._execute(job)
            status = "ok"
        except Exception as exc:  # noqa: BLE001 - record job failure
            message = str(exc)
            status = "error"
        finished = CronStore.timestamp()
        result = CronRunResult(
            job_id=job.id,
            run_id=run_id,
            status=status,  # type: ignore[arg-type]
            message=message,
            started_at=started,
            finished_at=finished,
        )
        self.store.write_run(result)
        self.store.update_job_state(
            job.id,
            last_run_at=finished,
            last_status=status,
            running=False,
        )
        now = datetime.now(timezone.utc)
        if job.schedule.kind == "at" and status == "ok" and job.delete_after_run:
            self.store.remove_job(job.id)
        else:
            nxt = _next_run(job.schedule, now)
            update: dict[str, Any] = {"running": False}
            if nxt is not None:
                update["next_run_at"] = format_timestamp(nxt)
            elif job.schedule.kind == "at":
                update["next_run_at"] = None
            self.store.update_job_state(job.id, **update)
        self.memory.append_daily(f"cron {job.name} ({job.id}): {status} — {message[:200]}")
        return result

    def tick(self, *, dry_run: bool = False) -> list[CronRunResult]:
        results: list[CronRunResult] = []
        now = datetime.now(timezone.utc)
        for job in self.due_jobs(now=now):
            self.store.update_job_state(job.id, running=True)
            results.append(self.run_job(job, dry_run=dry_run))
        return results

    def _execute(self, job: CronJob) -> str:
        payload = job.payload
        if job.service == "noop":
            return "noop ok"
        if job.service == "memory_append":
            text = str(payload.get("text") or payload.get("message") or job.name)
            path = self.memory.remember(text)
            return f"appended memory: {path}"
        if job.service == "shell":
            command = payload.get("command")
            if not command:
                raise ValueError("shell jobs require payload.command")
            if isinstance(command, str):
                command_list = command
            else:
                command_list = [str(part) for part in command]
            proc = subprocess.run(
                command_list,
                cwd=str(self.manifest.workspace_dir),
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}")
            return (proc.stdout or "shell ok").strip()[:500]
        if job.service == "codex_turn":
            from ..codex_launcher import build_invocation, dry_run_command
            from ..prompts import build_codex_turn_message

            message = build_codex_turn_message(self.manifest, job)
            inv = build_invocation(self.manifest, message)
            return dry_run_command(inv)
        if job.service in {"fdd_batch", "health_bridge", "health_hvac", "webhook"}:
            target = payload.get("url") or payload.get("endpoint") or payload.get("script")
            return f"queued {job.service} target={target or 'workspace'}"
        raise ValueError(f"unsupported service: {job.service}")
