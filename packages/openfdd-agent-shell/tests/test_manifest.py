from pathlib import Path

from openfdd_agent_shell.manifest import Manifest


def test_load_example_manifest(repo_root: Path) -> None:
    manifest_path = repo_root / "openfdd.toml.example"
    manifest = Manifest.load(manifest_path, repo_root)
    assert manifest.project_name == "my-fdd-workspace"
    assert "engine-pandas-fdd" in manifest.agent_skills
    assert manifest.build_deploy == "local"
    assert manifest.memory.bootstrap_max_chars == 12000
    assert manifest.cron.timezone == "UTC"
    assert "workspace-memory" in manifest.agent_skills


def test_build_invocation_dry_run(repo_root: Path) -> None:
    from openfdd_agent_shell.codex_launcher import build_invocation, dry_run_command

    manifest = Manifest.load(repo_root / "openfdd.toml.example", repo_root)
    inv = build_invocation(manifest, "hello")
    cmd = dry_run_command(inv)
    assert "codex" in cmd
    assert "hello" in cmd
    assert "Open-FDD agent session" in inv.system_prompt
