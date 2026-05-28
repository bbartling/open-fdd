from openfdd_agent_shell.manifest import Manifest
from openfdd_agent_shell.tui import run_repl


def test_repl_memory_and_cron_commands(repo_root, tmp_path, monkeypatch, capsys):
    manifest_path = tmp_path / "openfdd.toml"
    manifest_path.write_text((repo_root / "openfdd.toml.example").read_text(encoding="utf-8"), encoding="utf-8")
    manifest = Manifest.load(manifest_path, tmp_path)
    inputs = iter(
        [
            "/memory remember economizer fixed on site 2",
            "/cron list",
            "/quit",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
    assert run_repl(manifest, dry_run=True) == 0
    out = capsys.readouterr().out
    assert "economizer" in out.lower() or "remembered" in out.lower()
