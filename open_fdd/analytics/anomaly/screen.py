"""Orchestrate load → detect → rank → write for one device folder."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def screen_folder(
    folder: Path | str,
    out_dir: Path | str,
    *,
    top_n: int = 5,
    max_days: int = 10,
    methods: list[str] | tuple[str, ...] | None = None,
    command: str | None = None,
) -> Any:
    """Screen AHU IO points. Implemented in a later task."""
    raise NotImplementedError("screen_folder")
