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

