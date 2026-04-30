"""Shared typing protocol for drivers that persist pandas frames."""

from __future__ import annotations

from typing import Protocol

import pandas as pd


class FrameStore(Protocol):
    def write_frame(self, *, source: str, site_id: str, frame: pd.DataFrame) -> str: ...
