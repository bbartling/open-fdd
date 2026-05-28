"""Open-FDD workspace paths for BACnet commissioning and poll output."""

from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    return Path(os.environ.get("OPENFDD_REPO_ROOT", Path.cwd())).resolve()


def workspace_dir() -> Path:
    rel = os.environ.get("OPENFDD_WORKSPACE_DIR", "workspace").strip() or "workspace"
    root = repo_root()
    p = Path(rel)
    return (p if p.is_absolute() else root / p).resolve()


def bacnet_root() -> Path:
    return workspace_dir() / "bacnet"


def commissioning_dir() -> Path:
    return bacnet_root() / "commissioning"


def polls_dir() -> Path:
    return bacnet_root() / "polls"


def jobs_dir() -> Path:
    return bacnet_root() / "jobs"


def default_points_discovered() -> Path:
    return commissioning_dir() / "points_discovered.csv"


def default_points_enabled() -> Path:
    return commissioning_dir() / "points.csv"


def default_devices_discovered() -> Path:
    return commissioning_dir() / "devices_discovered.csv"


def ensure_layout() -> None:
    for d in (commissioning_dir(), polls_dir(), jobs_dir()):
        d.mkdir(parents=True, exist_ok=True)
