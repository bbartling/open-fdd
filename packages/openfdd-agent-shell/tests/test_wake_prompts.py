from openfdd_agent_shell.cron.models import CronJob, Schedule
from openfdd_agent_shell.manifest import Manifest
from openfdd_agent_shell.prompts import build_codex_turn_message


def test_codex_turn_wake_modes(repo_root, tmp_path):
    manifest = Manifest.load(repo_root / "openfdd.toml.example", tmp_path)
    job = CronJob(
        id="wake-mini",
        name="nightly-mini",
        schedule=Schedule(kind="every", every_seconds=3600),
        service="codex_turn",
        payload={"wake_mode": "mini"},
    )
    mini = build_codex_turn_message(manifest, job)
    assert "working-divergence.md" in mini
    assert "append one dated block" in mini

    job.payload = {"wake_mode": "critique"}
    critique = build_codex_turn_message(manifest, job)
    assert "promoted or superseded" in critique
