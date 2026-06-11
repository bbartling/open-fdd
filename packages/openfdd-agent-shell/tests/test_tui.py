import shutil

from openfdd_agent_shell.manifest import Manifest
from openfdd_agent_shell.tui import run_repl


def _manifest_in_tmp(repo_root, tmp_path):
    shutil.copy(repo_root / "openfdd.toml.example", tmp_path / "openfdd.toml.example")
    return Manifest.load(tmp_path / "openfdd.toml.example", tmp_path)


def test_repl_skills_command_lists_selected_skills(repo_root, tmp_path, monkeypatch, capsys):
    manifest = _manifest_in_tmp(repo_root, tmp_path)
    inputs = iter(["/skills", "/quit"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
    assert run_repl(manifest, dry_run=True) == 0
    out = capsys.readouterr().out
    assert "openfdd-mcp-server" in out


def test_repl_verify_prints_codex_command(repo_root, tmp_path, monkeypatch, capsys):
    manifest = _manifest_in_tmp(repo_root, tmp_path)
    inputs = iter(["/verify", "/quit"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
    assert run_repl(manifest, dry_run=True) == 0
    out = capsys.readouterr().out
    assert "codex" in out.lower()


def test_repl_engine_check_reports_import(repo_root, tmp_path, monkeypatch, capsys):
    manifest = _manifest_in_tmp(repo_root, tmp_path)
    inputs = iter(["/engine-check", "/quit"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
    assert run_repl(manifest, dry_run=True) == 0
    out = capsys.readouterr().out
    assert "open_fdd.arrow_runtime import OK" in out
