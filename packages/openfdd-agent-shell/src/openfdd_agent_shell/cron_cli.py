from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path

from .cron.models import CronJob, Schedule
from .cron.scheduler import CronScheduler
from .cron.store import CronStore
from .manifest import Manifest


def _load_manifest(repo_root: Path, manifest_path: Path | None) -> Manifest:
    path = manifest_path or (repo_root / "openfdd.toml")
    if not path.is_file():
        path = repo_root / "openfdd.toml.example"
    if not path.is_file():
        raise SystemExit(f"Manifest not found: {path}")
    manifest = Manifest.load(path, repo_root)
    manifest.ensure_workspace_dirs()
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Open-FDD workspace cron")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", type=Path, default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List cron jobs")
    add = sub.add_parser("add", help="Add a cron job")
    add.add_argument("--name", required=True)
    add.add_argument("--service", default="noop")
    add.add_argument("--every-seconds", type=int, default=None)
    add.add_argument("--at", dest="at_iso", default=None)
    add.add_argument("--cron", dest="cron_expr", default=None)
    add.add_argument("--payload-json", default="{}")
    add.add_argument("--delete-after-run", action="store_true")

    run = sub.add_parser("run", help="Run one job by id")
    run.add_argument("job_id")
    run.add_argument("--dry-run", action="store_true")

    tick = sub.add_parser("tick", help="Run all due jobs once")
    tick.add_argument("--dry-run", action="store_true")

    runs = sub.add_parser("runs", help="Show recent run records for a job")
    runs.add_argument("job_id")

    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    manifest = _load_manifest(repo_root, args.manifest)
    store = CronStore.from_manifest(manifest)
    scheduler = CronScheduler(manifest)

    if args.command == "list":
        for job in store.load_jobs():
            state = store.job_state(job.id)
            print(
                f"{job.id}\t{job.name}\t{job.service}\t"
                f"next={state.get('next_run_at')}\tenabled={job.enabled}"
            )
        return 0

    if args.command == "add":
        schedule_flags = sum(
            1
            for flag in (args.every_seconds, args.at_iso, args.cron_expr)
            if flag is not None and str(flag).strip() != ""
        )
        if schedule_flags != 1:
            raise SystemExit("exactly one of --every-seconds, --at, or --cron is required")
        if args.every_seconds is not None:
            schedule = Schedule(kind="every", every_seconds=args.every_seconds)
        elif args.at_iso:
            schedule = Schedule(kind="at", at_iso=args.at_iso)
        else:
            schedule = Schedule(
                kind="cron",
                cron_expr=args.cron_expr,
                timezone=manifest.cron.timezone,
            )
        try:
            payload = json.loads(args.payload_json)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"invalid --payload-json: {exc}") from exc
        job = CronJob(
            id=uuid.uuid4().hex[:12],
            name=args.name,
            schedule=schedule,
            service=args.service,  # type: ignore[arg-type]
            delete_after_run=bool(args.delete_after_run),
            payload=payload,
        )
        store.add_job(job)
        scheduler.store.update_job_state(job.id, next_run_at=None)
        print(job.id)
        return 0

    if args.command == "run":
        job = store.get_job(args.job_id)
        if job is None:
            raise SystemExit(f"unknown job: {args.job_id}")
        result = scheduler.run_job(job, dry_run=args.dry_run)
        print(f"{result.status}: {result.message}")
        return 0 if result.status != "error" else 1

    if args.command == "tick":
        results = scheduler.tick(dry_run=args.dry_run)
        for result in results:
            print(f"{result.job_id}\t{result.status}\t{result.message}")
        return 0

    if args.command == "runs":
        job_dir = store.runs_dir / args.job_id
        if not job_dir.is_dir():
            print("(no runs)")
            return 0
        for path in sorted(job_dir.glob("*.json"))[-10:]:
            print(path.read_text(encoding="utf-8"))
        return 0

    raise SystemExit(f"unknown command: {args.command}")
