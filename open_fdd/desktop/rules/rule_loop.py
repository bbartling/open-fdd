from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd

from open_fdd import RuleRunner


@dataclass
class RuleLoopConfig:
    rules_path: str
    timestamp_col: str = "timestamp"
    chunk_rows: int = 0
    target_memory_fraction: float = 0.25


def _estimate_chunk_rows(frame: pd.DataFrame, target_memory_fraction: float = 0.25) -> int:
    try:
        import psutil

        avail = int(psutil.virtual_memory().available * max(0.05, min(0.9, target_memory_fraction)))
        row_size = max(1, int(frame.memory_usage(deep=True).sum() / max(len(frame.index), 1)))
        return max(5000, avail // row_size)
    except ImportError:
        return 250000


def _iter_chunks(frame: pd.DataFrame, size: int) -> Iterable[pd.DataFrame]:
    for start in range(0, len(frame.index), size):
        yield frame.iloc[start : start + size].copy()


def run_rule_loop_batched(frame: pd.DataFrame, config: RuleLoopConfig) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    runner = RuleRunner(rules_path=config.rules_path)
    chunk_rows = int(config.chunk_rows or 0)
    if chunk_rows <= 0:
        chunk_rows = _estimate_chunk_rows(frame, config.target_memory_fraction)
    if len(frame.index) <= chunk_rows:
        return runner.run(frame, timestamp_col=config.timestamp_col).reset_index(drop=True)
    results: list[pd.DataFrame] = []
    for chunk in _iter_chunks(frame, chunk_rows):
        out = runner.run(chunk, timestamp_col=config.timestamp_col)
        results.append(out)
    return pd.concat(results, ignore_index=True)

