from __future__ import annotations

import json
from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any

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
    preview_rows: list[dict[str, Any]] | None = None


def _preview_rows_from_frame(frame: pd.DataFrame, n: int = 8) -> list[dict[str, Any]]:
    """JSON-safe first rows for UI verification (timestamps as ISO strings)."""
    if frame.empty:
        return []
    view = frame.head(n).copy()
    view = view.where(pd.notnull(view), None)
    if "timestamp" in view.columns:
        view = view.copy()
        view["timestamp"] = view["timestamp"].astype(str)
    blob = view.to_json(orient="records", date_format="iso", double_precision=15)
    return json.loads(blob) if blob else []


def _read_csv_frame(path: Path) -> pd.DataFrame:
    """
    Read CSV/TSV with common Grafana / Windows exports: UTF-16 LE with BOM, tab-separated, ``ts`` time column.
    """
    head = path.read_bytes()[:2]
    if head == b"\xff\xfe":
        return pd.read_csv(path, sep="\t", encoding="utf-16")
    if head == b"\xfe\xff":
        return pd.read_csv(path, sep="\t", encoding="utf-16-be")

    last_err: Exception | None = None
    for enc in ("utf-8-sig", "utf-8"):
        try:
            first_line = path.read_text(encoding=enc).split("\n", 1)[0]
        except UnicodeDecodeError as exc:
            last_err = exc
            continue
        sep = "\t" if first_line.count("\t") > first_line.count(",") else ","
        try:
            return pd.read_csv(path, sep=sep, encoding=enc)
        except (UnicodeDecodeError, pd.errors.ParserError) as exc:
            last_err = exc
            continue

    try:
        return pd.read_csv(path, sep="\t", encoding="utf-16")
    except Exception as exc:
        last_err = exc
    if last_err is not None:
        raise last_err
    raise ValueError(f"Could not read CSV: {path}")


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
        frame = _read_csv_frame(path)
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
            frame,
            candidate_names=("timestamp", "time", "date", "datetime", "ts"),
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
    preview = _preview_rows_from_frame(frame, n=8) if kept_len else None
    out = store.write_frame(source=source, site_id=site_id, frame=frame)
    return CsvIngestResult(
        rows=kept_len,
        dropped_rows=original_len - kept_len,
        file_path=out,
        timestamp_column=ts_col,
        metric_columns=metric_columns,
        preview_rows=preview,
    )
