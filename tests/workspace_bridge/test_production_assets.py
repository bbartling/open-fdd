"""CI guard: committed production dashboard assets must not embed private LAN or bench defaults."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CHECK = REPO / "scripts" / "check_production_assets.py"
ASSET_DIR = REPO / "workspace" / "api" / "static" / "app" / "assets"


def test_production_assets_exclude_private_lan_and_bench_defaults() -> None:
    """Scan shipped static assets (built in CI security job and committed to repo)."""
    assert ASSET_DIR.is_dir(), "static/app/assets missing — run dashboard production build"
    assert list(ASSET_DIR.glob("*.js")), "no JS bundle in static/app/assets"
    proc = subprocess.run(
        [sys.executable, str(CHECK)],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
