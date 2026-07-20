"""Persist the last browser zip upload across Streamlit refreshes until Clear session.

Writes a small pointer (``.last_browser_session.json``) next to the app so a new
browser session can reload from the still-extracted workdir without re-uploading.
``Clear session`` deletes the pointer and wipes the temp dir.

Env:
- ``VIBE19_BROWSER_SESSION_PATH`` — override pointer file location (tests use a temp path).
- ``VIBE19_BROWSER_AUTOLOAD=0`` — disable restore (AppTest / CI).
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BROWSER_SESSION_SCHEMA = "openfdd_browser_session_v1"
DEFAULT_BROWSER_SESSION_NAME = ".last_browser_session.json"


def app_root() -> Path:
    return Path(__file__).resolve().parent.parent


def default_browser_session_path() -> Path:
    env = (os.environ.get("VIBE19_BROWSER_SESSION_PATH") or "").strip()
    if env:
        return Path(env).expanduser()
    return app_root() / DEFAULT_BROWSER_SESSION_NAME


def browser_autoload_enabled() -> bool:
    raw = (os.environ.get("VIBE19_BROWSER_AUTOLOAD") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def write_browser_session_pointer(
    *,
    workdir: Path | str,
    building_root: Path | str,
    building_id: str,
    source: str = "",
    path: Path | str | None = None,
) -> Path:
    """Write / refresh the pointer file for the active uploaded package."""
    target = Path(path) if path else default_browser_session_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": BROWSER_SESSION_SCHEMA,
        "workdir": str(Path(workdir).resolve()),
        "building_root": str(Path(building_root).resolve()),
        "building_id": str(building_id or ""),
        "source": str(source or ""),
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    # Keep sweep_old_temp_dirs from reclaiming an active session
    touch_path(workdir)
    return target


def read_browser_session_pointer(path: Path | str | None = None) -> dict[str, Any] | None:
    p = Path(path) if path else default_browser_session_path()
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("schema_version") not in {BROWSER_SESSION_SCHEMA, "v1"}:
        return None
    return data


def clear_browser_session_pointer(path: Path | str | None = None) -> None:
    p = Path(path) if path else default_browser_session_path()
    try:
        p.unlink(missing_ok=True)
    except OSError:
        pass


def touch_path(path: Path | str | None) -> None:
    """Bump mtime so TEMP_MAX_AGE_SEC sweep does not delete an active workdir."""
    if not path:
        return
    p = Path(path)
    if not p.exists():
        return
    try:
        p.touch()
    except OSError:
        try:
            now = time.time()
            os.utime(p, (now, now))
        except OSError:
            pass


def pointer_paths_exist(pointer: dict[str, Any]) -> bool:
    wd = Path(str(pointer.get("workdir") or ""))
    br = Path(str(pointer.get("building_root") or ""))
    return wd.is_dir() and br.is_dir() and (br / "manifest.json").is_file()
