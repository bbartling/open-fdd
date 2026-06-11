from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import open_fdd

ROOT = Path(__file__).resolve().parents[2]


def test_pyproject_matches_init_version():
    assert open_fdd.__version__
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "release" / "check_version.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
