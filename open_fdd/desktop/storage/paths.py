from __future__ import annotations

import os
from pathlib import Path


def desktop_data_dir() -> Path:
    """
    Per-user writable data path.
    """
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    path = base / "open-fdd-desktop"
    path.mkdir(parents=True, exist_ok=True)
    return path


def model_json_path() -> Path:
    return desktop_data_dir() / "model.json"


def model_ttl_path() -> Path:
    return desktop_data_dir() / "data_model.ttl"


def feather_root() -> Path:
    root = desktop_data_dir() / "feather_store"
    root.mkdir(parents=True, exist_ok=True)
    return root

