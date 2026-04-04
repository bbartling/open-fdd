import subprocess
from pathlib import Path


def test_bootstrap_help_lists_mode_flag():
    script = Path("scripts/bootstrap.sh")
    res = subprocess.run(
        [str(script), "--help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res.returncode == 0
    assert "--mode MODE" in res.stdout
    assert "collector" in res.stdout
    assert "model" in res.stdout
    assert "engine" in res.stdout
    assert "full" in res.stdout
    assert "--bacnet-instance" in res.stdout
    assert "--bacnet-address" in res.stdout
    assert "open-fdd" in res.stdout
    assert "--bacnet-name" not in res.stdout
    assert "--allow-no-ui-auth" in res.stdout
    assert "--doctor" in res.stdout


def test_bootstrap_rejects_invalid_mode():
    script = Path("scripts/bootstrap.sh")
    res = subprocess.run(
        [str(script), "--mode", "not-a-mode"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res.returncode == 1
    out = (res.stdout or "") + (res.stderr or "")
    assert "Invalid --mode" in out


def test_bootstrap_frontend_test_path_has_host_fallback_docs():
    script_text = Path("scripts/bootstrap.sh").read_text(encoding="utf-8")
    assert "Frontend container test path failed; attempting host npm fallback" in script_text
    assert "Frontend: OK (via host npm fallback)" in script_text

