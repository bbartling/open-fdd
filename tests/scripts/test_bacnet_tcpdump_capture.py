"""Argument parsing / dry-run for bacnet_tcpdump_capture.sh"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "bacnet_tcpdump_capture.sh"


def test_bacnet_tcpdump_dry_run():
    proc = subprocess.run(
        [str(SCRIPT), "--interface", "eth0", "--minutes", "1", "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "DRY-RUN" in proc.stdout
    assert "eth0" in proc.stdout
