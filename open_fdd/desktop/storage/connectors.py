from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import pandas as pd

from open_fdd.desktop.storage.feather_store import FeatherStore


class TimeSeriesConnector(Protocol):
    """
    Generic desktop connector contract for time-series I/O.
    """

    def write_frame(self, *, source: str, site_id: str, frame: pd.DataFrame) -> str: ...

    def read_frame(self, *, source: str, site_id: str) -> pd.DataFrame: ...


@dataclass
class FeatherConnector:
    store: FeatherStore

    def write_frame(self, *, source: str, site_id: str, frame: pd.DataFrame) -> str:
        return str(self.store.write_frame(source=source, site_id=site_id, frame=frame))

    def read_frame(self, *, source: str, site_id: str) -> pd.DataFrame:
        return self.store.read_site_frames(source=source, site_id=site_id)


@dataclass
class SqliteConnector:
    """
    Generic SQL-like connector for desktop mode.
    Stores timeseries in a local sqlite table (no web, no docker).
    """

    db_path: str
    table_name: str = "timeseries_readings"

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

