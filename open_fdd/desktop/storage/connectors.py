from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Protocol

import pandas as pd

from open_fdd.desktop.storage.feather_store import FeatherStore


class TimeSeriesConnector(Protocol):
    """
    Generic desktop connector contract for time-series I/O.
    """

    def write_frame(self, *, source: str, site_id: str, frame: pd.DataFrame) -> str: ...

    def read_frame(self, *, source: str, site_id: str) -> pd.DataFrame: ...

    def ingest_csv(self, *, csv_path: str, source: str, site_id: str) -> dict: ...

    def purge(self, *, source: str | None = None, site_id: str | None = None) -> dict[str, int]: ...


@dataclass
class FeatherConnector:
    store: FeatherStore

    def write_frame(self, *, source: str, site_id: str, frame: pd.DataFrame) -> str:
        return str(self.store.write_frame(source=source, site_id=site_id, frame=frame))

    def read_frame(self, *, source: str, site_id: str) -> pd.DataFrame:
        return self.store.read_site_frames(source=source, site_id=site_id)

    def ingest_csv(self, *, csv_path: str, source: str, site_id: str) -> dict:
        from open_fdd.platform.drivers.csv_driver import ingest_csv_to_feather

        result = ingest_csv_to_feather(csv_path=csv_path, source=source, site_id=site_id, store=self.store)
        out: dict[str, Any] = {
            "rows": result.rows,
            "dropped_rows": result.dropped_rows,
            "storage_path": str(result.file_path),
            "feather_path": str(result.file_path),
            "metrics": result.metric_columns,
        }
        if result.error:
            out["parse_error"] = result.error
        if result.preview_rows is not None:
            out["preview_rows"] = result.preview_rows
        return out

    def purge(self, *, source: str | None = None, site_id: str | None = None) -> dict[str, int]:
        return self.store.purge(source=source, site_id=site_id)


@dataclass
class SqliteConnector:
    """
    Generic SQL-like connector for desktop mode.
    Stores timeseries in a local sqlite table (no web, no docker).
    """

    db_path: str
    table_name: str = "timeseries_readings"

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", self.table_name):
            raise ValueError(f"Unsafe table_name '{self.table_name}'. Use letters/digits/underscore and start with a letter/_")

    def _ensure_schema(self) -> None:
        import sqlite3

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.table_name} (
                    source TEXT NOT NULL,
                    site_id TEXT NOT NULL,
                    ts TEXT NOT NULL,
                    metric TEXT NOT NULL,
                    value REAL
                )
                """
            )

    def write_frame(self, *, source: str, site_id: str, frame: pd.DataFrame) -> str:
        import sqlite3

        self._ensure_schema()
        if frame.empty:
            return self.db_path
        ts_col = "timestamp" if "timestamp" in frame.columns else frame.columns[0]
        melted = frame.copy().melt(id_vars=[ts_col], var_name="metric", value_name="value")
        melted = melted.rename(columns={ts_col: "ts"})
        melted["source"] = source
        melted["site_id"] = site_id
        rows = melted[["source", "site_id", "ts", "metric", "value"]]
        with sqlite3.connect(self.db_path) as conn:
            rows.to_sql(self.table_name, conn, if_exists="append", index=False)
        return self.db_path

    def read_frame(self, *, source: str, site_id: str) -> pd.DataFrame:
        import sqlite3

        self._ensure_schema()
        with sqlite3.connect(self.db_path) as conn:
            rows = pd.read_sql_query(
                f"SELECT ts, metric, value FROM {self.table_name} WHERE source = ? AND site_id = ? ORDER BY ts",
                conn,
                params=[source, site_id],
            )
        if rows.empty:
            return pd.DataFrame()
        wide = rows.pivot_table(index="ts", columns="metric", values="value", aggfunc="last").reset_index()
        wide = wide.rename(columns={"ts": "timestamp"})
        return wide

    def ingest_csv(self, *, csv_path: str, source: str, site_id: str) -> dict:
        from open_fdd.desktop.services.time_utils import (
            infer_timestamp_column,
            normalize_known_timezone_abbreviations,
            parse_timestamp_series,
        )

        frame = pd.read_csv(csv_path)
        original_len = len(frame.index)
        if frame.empty:
            metrics: list[str] = []
            dropped_rows = 0
            rows = 0
        else:
            ts_col = infer_timestamp_column(frame, candidate_names=("timestamp", "time", "date", "datetime"))
            try:
                frame[ts_col] = parse_timestamp_series(frame, timestamp_col=ts_col, min_valid_ratio=0.35)
            except ValueError:
                frame[ts_col] = pd.to_datetime(
                    normalize_known_timezone_abbreviations(frame[ts_col]),
                    errors="coerce",
                    utc=True,
                )
            frame = frame[frame[ts_col].notna()].copy()
            if ts_col != "timestamp":
                frame = frame.rename(columns={ts_col: "timestamp"})
                ts_col = "timestamp"
            ordered = [ts_col] + [c for c in frame.columns if c != ts_col]
            frame = frame[ordered]
            metrics = [str(c) for c in frame.columns if str(c) != "timestamp"]
            rows = len(frame.index)
            dropped_rows = original_len - rows
        out = self.write_frame(source=source, site_id=site_id, frame=frame)
        ret: dict[str, Any] = {
            "rows": rows,
            "dropped_rows": dropped_rows,
            "storage_path": out,
            "feather_path": "",
            "metrics": metrics,
        }
        from open_fdd.desktop.services.timeseries_numeric_clean import preview_rows_json

        ret["preview_rows"] = preview_rows_json(frame, 8) if not frame.empty else []
        return ret

    def purge(self, *, source: str | None = None, site_id: str | None = None) -> dict[str, int]:
        import sqlite3

        self._ensure_schema()
        where_parts: list[str] = []
        params: list[str] = []
        if source is not None:
            where_parts.append("source = ?")
            params.append(str(source))
        if site_id is not None:
            where_parts.append("site_id = ?")
            params.append(str(site_id))
        where_sql = f" WHERE {' AND '.join(where_parts)}" if where_parts else ""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(f"DELETE FROM {self.table_name}{where_sql}", params)
            return {"files_deleted": int(cur.rowcount or 0), "dirs_deleted": 0, "bytes_deleted": 0}

