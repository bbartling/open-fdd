from __future__ import annotations

import os
from pathlib import Path
import sys


def desktop_data_dir() -> Path:
    """
    Per-user writable data path.
    """
    override = str(os.getenv("OFDD_DESKTOP_DATA_DIR", "")).strip()
    if override:
        path = Path(override).expanduser()
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    path = base / "open-fdd-desktop"
    path.mkdir(parents=True, exist_ok=True)
    return path


def model_json_path() -> Path:
    return desktop_data_dir() / "model.json"


def model_ttl_path() -> Path:
    override = str(os.getenv("OFDD_MODEL_TTL_PATH", "")).strip()
    if override:
        path = Path(override).expanduser()
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        return path
    return desktop_data_dir() / "data_model.ttl"


def model_ttl_mirror_path() -> Path | None:
    override = str(os.getenv("OFDD_MODEL_TTL_MIRROR_PATH", "")).strip()
    if not override:
        return None
    path = Path(override).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    return path


def feather_root() -> Path:
    root = desktop_data_dir() / "feather_store"
    root.mkdir(parents=True, exist_ok=True)
    return root


def default_rules_root() -> Path:
    root = desktop_data_dir() / "rules"
    root.mkdir(parents=True, exist_ok=True)
    return root

