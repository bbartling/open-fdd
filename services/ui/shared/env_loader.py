"""Load .env files before DataConfig reads HVAC_* variables."""

from __future__ import annotations

import os
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent


def _candidate_env_files() -> list[Path]:
    cwd = Path.cwd()
    seen: set[Path] = set()
    out: list[Path] = []
    for path in (
        APP_ROOT / ".env",
        cwd / ".env",
        cwd.parent / ".env",
    ):
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        out.append(path)
    return out


def load_env_files(*, override: bool = False) -> Path | None:
    """Load the first existing .env file found. Returns path loaded or None."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return None

    for path in _candidate_env_files():
        if path.is_file():
            load_dotenv(path, override=override)
            return path
    return None


def resolve_data_path(raw: str | os.PathLike[str]) -> Path:
    """Normalize cross-platform paths; resolve relative paths against APP_ROOT."""
    text = str(raw).strip().strip('"').strip("'")
    if not text:
        return Path(text)
    path = Path(text)
    if not path.is_absolute():
        path = (APP_ROOT / path).resolve()
    else:
        path = path.resolve()
    return path
