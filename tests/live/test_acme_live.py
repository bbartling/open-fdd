"""Optional live Acme validation (skipped unless ACME_VALIDATE_LIVE=1)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(os.environ.get("ACME_VALIDATE_LIVE") != "1", reason="Set ACME_VALIDATE_LIVE=1")
def test_live_acme_quick_validation():
    base = os.environ.get("ACME_BASE_URL", "").strip()
    if not base:
        secrets = REPO / "infra/ansible/secrets/acme.env.local"
        if secrets.is_file():
            for line in secrets.read_text(encoding="utf-8").splitlines():
                if "ACME_SSH_HOST=" in line:
                    host = line.split("=", 1)[1].strip().strip("'\"")
                    base = f"http://{host}"
                    break
    if not base:
        pytest.skip("ACME_BASE_URL or acme.env.local required")
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts/acme_live_validate.py"),
            "--base",
            base,
            "--quick",
            "--site-id",
            os.environ.get("ACME_SITE_ID", "acme"),
        ],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
