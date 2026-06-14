"""CI guard: production dashboard assets must not embed private LAN or bench defaults."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CHECK = REPO / "scripts" / "check_production_assets.py"
DASHBOARD = REPO / "workspace" / "dashboard"


def test_production_assets_exclude_private_lan_and_bench_defaults() -> None:
    """Build dashboard and scan shipped static assets."""
    subprocess.run(
        ["npm", "run", "build"],
        cwd=DASHBOARD,
        check=True,
        capture_output=True,
        text=True,
    )
    proc = subprocess.run(
        [sys.executable, str(CHECK)],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
