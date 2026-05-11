from openfdd_agent_shell.manifest import Manifest
from openfdd_agent_shell.tui import run_repl


def test_repl_skills_command_lists_selected_skills(repo_root, monkeypatch, capsys):
    manifest = Manifest.load(repo_root / "openfdd.toml.example", repo_root)
    inputs = iter(["/skills", "/quit"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
    assert run_repl(manifest, dry_run=True) == 0
    out = capsys.readouterr().out
    assert "engine-pandas-fdd" in out


def test_repl_verify_prints_codex_command(repo_root, monkeypatch, capsys):
    manifest = Manifest.load(repo_root / "openfdd.toml.example", repo_root)
    inputs = iter(["/verify", "/quit"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
    assert run_repl(manifest, dry_run=True) == 0
    out = capsys.readouterr().out
    assert "codex" in out.lower()


def test_repl_engine_check_reports_import(repo_root, monkeypatch, capsys):
    manifest = Manifest.load(repo_root / "openfdd.toml.example", repo_root)
    inputs = iter(["/engine-check", "/quit"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
    assert run_repl(manifest, dry_run=True) == 0
    out = capsys.readouterr().out
    assert "open_fdd.engine import OK" in out
