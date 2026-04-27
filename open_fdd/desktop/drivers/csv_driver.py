from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from open_fdd.desktop.storage.feather_store import FeatherStore


@dataclass
class CsvIngestResult:
    rows: int
    file_path: Path
    timestamp_column: str
    metric_columns: list[str]


def infer_timestamp_column(columns: list[str]) -> str:
    for col in columns:
        if str(col).strip().casefold() == "timestamp":
            return str(col)
    for col in columns:
        if "timestamp" in str(col).strip().casefold():
            return str(col)
    raise ValueError("CSV missing timestamp column")


def ingest_csv_to_feather(
    *,
    csv_path: str | Path,
    source: str,
    site_id: str,
    store: FeatherStore,
) -> CsvIngestResult:
    frame = pd.read_csv(csv_path)
    if frame.empty:
        out = store.write_frame(source=source, site_id=site_id, frame=frame)
        return CsvIngestResult(rows=0, file_path=out, timestamp_column="", metric_columns=[])
    ts_col = infer_timestamp_column([str(c) for c in frame.columns])
    frame[ts_col] = pd.to_datetime(frame[ts_col], errors="coerce", utc=True)
    frame = frame[frame[ts_col].notna()].copy()
    metric_columns = [str(c) for c in frame.columns if str(c) != ts_col]
    out = store.write_frame(source=source, site_id=site_id, frame=frame)
    return CsvIngestResult(
        rows=int(len(frame.index)),
        file_path=out,
        timestamp_column=ts_col,
        metric_columns=metric_columns,
    )

