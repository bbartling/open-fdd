from datetime import datetime, timedelta, timezone

from openfdd_agent_shell.cron.models import CronJob, Schedule
from openfdd_agent_shell.cron.scheduler import CronScheduler
from openfdd_agent_shell.cron.store import format_timestamp
from openfdd_agent_shell.manifest import Manifest


def test_cron_run_noop_and_tick(repo_root, tmp_path):
    manifest = Manifest.load(repo_root / "openfdd.toml.example", tmp_path)
    scheduler = CronScheduler(manifest)
    job = CronJob(
        id="job1",
        name="heartbeat",
        schedule=Schedule(kind="every", every_seconds=60),
        service="noop",
    )
    scheduler.store.add_job(job)
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    scheduler.store.update_job_state(job.id, next_run_at=format_timestamp(past))
    results = scheduler.tick()
    assert len(results) == 1
    assert results[0].status == "ok"


def test_memory_append_job(repo_root, tmp_path):
    manifest = Manifest.load(repo_root / "openfdd.toml.example", tmp_path)
    scheduler = CronScheduler(manifest)
    job = CronJob(
        id="job2",
        name="remember-health",
        schedule=Schedule(
            kind="at",
            at_iso=format_timestamp(datetime.now(timezone.utc)),
        ),
        service="memory_append",
        payload={"text": "AHU-1 economizer hunting resolved"},
        delete_after_run=True,
    )
    scheduler.store.add_job(job)
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    scheduler.store.update_job_state(job.id, next_run_at=format_timestamp(past))
    result = scheduler.run_job(job)
    assert result.status == "ok"
    assert scheduler.store.get_job(job.id) is None
