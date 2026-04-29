from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path

import pandas as pd

from open_fdd.desktop.services.time_utils import (
    infer_timestamp_column,
    normalize_known_timezone_abbreviations,
    parse_timestamp_series,
)
from open_fdd.desktop.storage.feather_store import FeatherStore


@dataclass
class CsvIngestResult:
    rows: int
    dropped_rows: int
    file_path: Path
    timestamp_column: str
    metric_columns: list[str]
    success: bool = True
    error: str | None = None


def ingest_csv_to_feather(
    *,
    csv_path: str | Path,
    source: str,
    site_id: str,
    store: FeatherStore,
) -> CsvIngestResult:
    log = logging.getLogger(__name__)
    path = Path(csv_path)
    try:
        frame = pd.read_csv(path)
    except FileNotFoundError as exc:
        msg = f"CSV not found: {path} ({exc})"
        log.error(msg)
        return CsvIngestResult(
            rows=0,
            dropped_rows=0,
            file_path=path,
            timestamp_column="",
            metric_columns=[],
            success=False,
            error=msg,
        )
    except pd.errors.ParserError as exc:
        msg = f"CSV parse error for {path}: {exc}"
        log.error(msg)
        return CsvIngestResult(
            rows=0,
            dropped_rows=0,
            file_path=path,
            timestamp_column="",
            metric_columns=[],
            success=False,
            error=msg,
        )
    except Exception as exc:  # noqa: BLE001
        msg = f"Failed reading CSV {path}: {exc}"
        log.exception(msg)
        return CsvIngestResult(
            rows=0,
            dropped_rows=0,
            file_path=path,
            timestamp_column="",
            metric_columns=[],
            success=False,
            error=msg,
        )

    if frame.empty:
        out = store.write_frame(source=source, site_id=site_id, frame=frame)
        return CsvIngestResult(rows=0, dropped_rows=0, file_path=out, timestamp_column="", metric_columns=[])

    try:
        ts_col = infer_timestamp_column(
            frame, candidate_names=("timestamp", "time", "date", "datetime")
        )
    except Exception as exc:  # noqa: BLE001
        msg = f"Could not infer timestamp column for {path}: {exc}"
        log.error(msg)
        return CsvIngestResult(
            rows=0,
            dropped_rows=0,
            file_path=path,
            timestamp_column="",
            metric_columns=[str(c) for c in frame.columns],
            success=False,
            error=msg,
        )

    original_len = len(frame.index)
    try:
        frame[ts_col] = parse_timestamp_series(frame, timestamp_col=ts_col, min_valid_ratio=0.35)
    except ValueError:
        # Keep ingest resilient for messy CSV files: fallback to best-effort parse and drop bad rows.
        frame[ts_col] = pd.to_datetime(
            normalize_known_timezone_abbreviations(frame[ts_col]), errors="coerce", utc=True
        )
    frame = frame[frame[ts_col].notna()].copy()
    kept_len = len(frame.index)
    metric_columns = [str(c) for c in frame.columns if str(c) != ts_col]
    out = store.write_frame(source=source, site_id=site_id, frame=frame)
    return CsvIngestResult(
        rows=kept_len,
        dropped_rows=original_len - kept_len,
        file_path=out,
        timestamp_column=ts_col,
        metric_columns=metric_columns,
    )

