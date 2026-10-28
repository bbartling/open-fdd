"""Prove W2a only added kind/effect metadata to registry and tuning catalog."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "ci"))

from unit_contract_lib import (  # noqa: E402
    assert_metadata_only_registry_diff,
    assert_metadata_only_tuning_diff,
)


def test_registry_metadata_only_diff_from_master() -> None:
    subprocess.run(["git", "fetch", "origin", "master"], cwd=ROOT, check=True)
    assert_metadata_only_registry_diff()


def test_tuning_catalog_metadata_only_diff_from_master() -> None:
    subprocess.run(["git", "fetch", "origin", "master"], cwd=ROOT, check=True)
    assert_metadata_only_tuning_diff()
