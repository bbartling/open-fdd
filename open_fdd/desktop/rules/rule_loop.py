from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd

from open_fdd.engine.runner import RuleRunner, load_rule


@dataclass
class RuleLoopConfig:
    rules_path: str
    timestamp_col: str = "timestamp"
    chunk_rows: int = 0
    target_memory_fraction: float = 0.25
    #: If set, only these YAML basenames (e.g. ``["ahu_sat.yaml"]``) are loaded from ``rules_path``.
    rule_files: list[str] | None = None
    #: When True, rules that reference missing columns are skipped instead of failing the whole run.
    skip_missing_columns: bool = False


def _load_rules_for_config(rules_path: str, rule_files: list[str] | None) -> list[dict]:
    path = Path(rules_path)
    if path.is_file():
        return [load_rule(path)]
    if not path.is_dir():
        return []
    wanted: set[str] | None = None
    if rule_files:
        wanted = {Path(str(n).strip()).name for n in rule_files if str(n).strip()}
    by_name: dict[str, Path] = {}
    for pattern in ("*.yaml", "*.yml"):
        for f in path.glob(pattern):
            by_name.setdefault(f.name, f)
    rules: list[dict] = []
    for name in sorted(by_name.keys()):
        f = by_name[name]
        if wanted is not None and f.name not in wanted:
            continue
        rules.append(load_rule(f))
    return rules


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
    rules = _load_rules_for_config(config.rules_path, config.rule_files)
    runner = RuleRunner(rules=rules)
    chunk_rows = int(config.chunk_rows or 0)
    if chunk_rows <= 0:
        chunk_rows = _estimate_chunk_rows(frame, config.target_memory_fraction)
    if len(frame.index) <= chunk_rows:
        return runner.run(
            frame,
            timestamp_col=config.timestamp_col,
            skip_missing_columns=config.skip_missing_columns,
        ).reset_index(drop=True)
    results: list[pd.DataFrame] = []
    for chunk in _iter_chunks(frame, chunk_rows):
        out = runner.run(
            chunk,
            timestamp_col=config.timestamp_col,
            skip_missing_columns=config.skip_missing_columns,
        )
        results.append(out)
    return pd.concat(results, ignore_index=True)

