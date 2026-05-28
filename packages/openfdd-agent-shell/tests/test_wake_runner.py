from openfdd_agent_shell.manifest import Manifest
from openfdd_agent_shell.memory.checkpoints import CheckpointStore
from openfdd_agent_shell.wake.runner import WakeRunner


def test_wake_runner_dry_run(repo_root, tmp_path):
    manifest = Manifest.load(repo_root / "openfdd.toml.example", tmp_path)
    manifest.ensure_workspace_dirs()
    result = WakeRunner(manifest).run(dry_run=True, mini_count=1)
    assert not result.debounced
    assert not result.locked
    assert result.log_path.is_file()
    text = result.log_path.read_text(encoding="utf-8")
    assert "mini 1/1" in text
    assert "critique" in text
    assert CheckpointStore(manifest.wake.checkpoints_file).read().startswith("# BUILD_CHECKPOINTS")
    assert manifest.wake.bootstrap_snapshot.is_file()
