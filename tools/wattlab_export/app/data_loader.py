"""Load historian CSV trees, uploads, SQLite/DuckDB into pandas DataFrames."""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd

TS_CANDIDATES = ("timestamp_utc", "timestamp", "time", "datetime", "date_time")


def detect_timestamp_column(df: pd.DataFrame) -> str | None:
    for c in TS_CANDIDATES:
        if c in df.columns:
            return c
    for c in df.columns:
        if "time" in c.lower() or "date" in c.lower():
            return c
    return None


def normalize_timestamp(df: pd.DataFrame, col: str | None = None) -> pd.DataFrame:
    out = df.copy()
    ts_col = col or detect_timestamp_column(out)
    if ts_col is None:
        return out
    out[ts_col] = pd.to_datetime(out[ts_col], utc=True, errors="coerce")
    out = out.dropna(subset=[ts_col])
    out = out.sort_values(ts_col).set_index(ts_col)
    out.index.name = "timestamp"
    return out


def infer_poll_seconds(df: pd.DataFrame) -> float:
    if not isinstance(df.index, pd.DatetimeIndex) or len(df.index) < 2:
        return 300.0
    deltas = df.index.to_series().diff().dropna().dt.total_seconds()
    if deltas.empty:
        return 300.0
    med = float(deltas.median())
    return med if med > 0 else 300.0


def validate_dataframe(df: pd.DataFrame) -> list[str]:
    issues: list[str] = []
    if df.empty:
        issues.append("DataFrame is empty")
    if not isinstance(df.index, pd.DatetimeIndex):
        issues.append("No datetime index — assign or detect timestamp column")
    if df.index.has_duplicates:
        issues.append(f"Duplicate timestamps: {int(df.index.duplicated().sum())}")
    return issues


def _read_columns_map(columns_path: Path) -> dict[str, str]:
    """col -> point_role or col name."""
    if not columns_path.is_file():
        return {}
    df = pd.read_csv(columns_path)
    col_key = "col" if "col" in df.columns else df.columns[0]
    role_key = next((c for c in ("point_role", "role", "description") if c in df.columns), None)
    out: dict[str, str] = {}
    for _, row in df.iterrows():
        col = str(row[col_key]).strip()
        if not col or col in ("col", "column"):
            continue
        role = str(row[role_key]).strip() if role_key else col
        out[col] = role
    return out


def load_equipment_csv(history_path: Path, columns_path: Path | None = None) -> pd.DataFrame:
    raw = pd.read_csv(history_path)
    ts = detect_timestamp_column(raw)
    df = normalize_timestamp(raw, ts)
    if columns_path and columns_path.is_file():
        _read_columns_map(columns_path)  # validate file exists
    return df


def discover_equipment(building_root: Path) -> list[dict[str, Any]]:
    """Find equipment folders with history_wide.csv + columns.csv.

    Skips ``weather`` folders (OAT is loaded separately, not as equipment).
    """
    found: list[dict[str, Any]] = []
    if not building_root.is_dir():
        return found
    skip_names = {"weather", "__macosx"}
    for path in building_root.rglob("history_wide.csv"):
        eq_dir = path.parent
        if any(part.lower() in skip_names for part in eq_dir.relative_to(building_root).parts):
            continue
        if eq_dir.name.lower() in skip_names:
            continue
        cols = eq_dir / "columns.csv"
        eq_id = eq_dir.name
        rel = eq_dir.relative_to(building_root)
        if len(rel.parts) > 1:
            eq_id = rel.parts[-1]
        found.append(
            {
                "equipment_id": eq_id,
                "history_path": path,
                "columns_path": cols if cols.is_file() else None,
                "folder": eq_dir,
            }
        )
    return sorted(found, key=lambda x: x["equipment_id"])


def list_building_candidates(path: Path) -> list[Path]:
    """Return building folders under ``path`` (or ``[path]`` if it already is one).

    A building folder is any directory that contains at least one ``history_wide.csv``
    (directly or nested under equipment subfolders).
    """
    path = Path(path)
    if not path.is_dir():
        return []
    if discover_equipment(path):
        return [path]
    kids = []
    for child in sorted(path.iterdir()):
        if child.is_dir() and discover_equipment(child):
            kids.append(child)
    return kids


def load_building_folder(building_folder: Path) -> dict[str, pd.DataFrame]:
    """Load one building folder (name is the building id — any label, not just BUILDING_100)."""
    building_folder = Path(building_folder)
    return load_building_tree(building_folder.parent, building_folder.name)


def load_building_tree(data_root: Path, building_id: str) -> dict[str, pd.DataFrame]:
    building_root = data_root / building_id
    manifest_path = building_root / "manifest.json"
    grid_minutes = 5
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        grid_minutes = int(manifest.get("grid_minutes", 5))
    out: dict[str, pd.DataFrame] = {}
    for eq in discover_equipment(building_root):
        df = load_equipment_csv(eq["history_path"], eq.get("columns_path"))
        df.attrs["poll_seconds"] = grid_minutes * 60.0
        df.attrs["equipment_id"] = eq["equipment_id"]
        df.attrs["columns_path"] = eq.get("columns_path")
        out[eq["equipment_id"]] = df
    return out


def load_uploaded_csv(file: BytesIO | Any) -> pd.DataFrame:
    raw = pd.read_csv(file)
    return normalize_timestamp(raw)


def load_local_folder(folder: Path) -> dict[str, pd.DataFrame]:
    return load_building_tree(folder.parent, folder.name) if (folder / "manifest.json").is_file() else {
        eq["equipment_id"]: load_equipment_csv(eq["history_path"], eq.get("columns_path"))
        for eq in discover_equipment(folder)
    }


def load_sqlite_table(db_path: Path, table: str, *, row_limit: int | None = None) -> pd.DataFrame:
    from app.sql_sources import load_sqlite_table as _load

    return _load(db_path, table, row_limit=row_limit)


def load_duckdb_query(db_path: Path, query: str) -> pd.DataFrame:
    from app.sql_sources import load_duckdb_query as _load

    return _load(db_path, query)


def load_parquet(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path)
    if not isinstance(df.index, pd.DatetimeIndex):
        df = normalize_timestamp(df)
    return df
