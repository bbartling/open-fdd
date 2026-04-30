from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_desktop_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure tests never read/write user runtime desktop data."""
    data_dir = tmp_path / "open-fdd-desktop-test-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(data_dir))
    monkeypatch.setenv("OFDD_MODEL_TTL_PATH", str(data_dir / "data_model.ttl"))
    monkeypatch.setenv("OFDD_MODEL_TTL_MIRROR_PATH", str(data_dir / "data_model_mirror.ttl"))
    # Keep tests deterministic on TTL loop cadence.
    monkeypatch.setenv("OFDD_TTL_SYNC_INTERVAL_SECONDS", "1")

