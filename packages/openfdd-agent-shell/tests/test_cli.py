from openfdd_agent_shell.cli import main


def test_cli_dry_run_message(repo_root, capsys):
    code = main(
        [
            "--repo-root",
            str(repo_root),
            "--manifest",
            str(repo_root / "openfdd.toml.example"),
            "--dry-run",
            "--message",
            "scaffold a csv ingest api",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "codex" in out.lower()
    assert "scaffold a csv ingest api" in out
