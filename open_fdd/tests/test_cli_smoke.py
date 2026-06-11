from __future__ import annotations

import subprocess
import sys


def test_cli_version():
    proc = subprocess.run(
        [sys.executable, "-m", "open_fdd.cli", "version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert proc.stdout.strip()
