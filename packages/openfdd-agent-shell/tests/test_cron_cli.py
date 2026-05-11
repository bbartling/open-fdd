from openfdd_agent_shell.cron_cli import main


def test_cron_cli_add_and_list(repo_root, tmp_path, capsys):
    manifest = tmp_path / "openfdd.toml"
    manifest.write_text((repo_root / "openfdd.toml.example").read_text(encoding="utf-8"), encoding="utf-8")
    code = main(
        [
            "--repo-root",
            str(tmp_path),
            "--manifest",
            str(manifest),
            "add",
            "--name",
            "health-check",
            "--every-seconds",
            "3600",
            "--service",
            "health_hvac",
            "--payload-json",
            "{\"site_ids\":[\"site-1\"]}",
        ]
    )
    assert code == 0
    job_id = capsys.readouterr().out.strip()
    capsys.readouterr()
    code = main(
        [
            "--repo-root",
            str(tmp_path),
            "--manifest",
            str(manifest),
            "list",
        ]
    )
    assert code == 0
    listed = capsys.readouterr().out
    assert job_id in listed
    assert "health_hvac" in listed
