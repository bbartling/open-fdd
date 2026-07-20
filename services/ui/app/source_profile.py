"""Profile and normalize CSV upload sources (wide / long / multi-file)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

import pandas as pd

from app.data_loader import detect_timestamp_column, normalize_timestamp, validate_dataframe


@dataclass
class RawSource:
    name: str
    df: pd.DataFrame
    bytes_size: int = 0
    format_hint: str = "unknown"


@dataclass
class SourceProfile:
    source_name: str
    format: str  # wide | long | unknown
    timestamp_column: str | None
    numeric_columns: list[str]
    row_count: int
    equipment_id_columns: list[str] = field(default_factory=list)
    point_name_columns: list[str] = field(default_factory=list)
    value_columns: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)


LONG_EQUIP_COLS = ("equipment_id", "equip_id", "equip", "device_id")
LONG_POINT_COLS = ("point_name", "point", "point_id", "variable", "tag")
LONG_VALUE_COLS = ("value", "val", "reading")


def profile_csv_source(df: pd.DataFrame, source_name: str = "upload") -> SourceProfile:
    ts = detect_timestamp_column(df)
    numeric = [c for c in df.columns if c != ts and pd.api.types.is_numeric_dtype(df[c])]
    issues: list[str] = []
    if ts is None:
        issues.append("No timestamp column detected")
    if not numeric:
        issues.append("No numeric data columns detected")

    equip_cols = [c for c in df.columns if c.lower() in LONG_EQUIP_COLS]
    point_cols = [c for c in df.columns if c.lower() in LONG_POINT_COLS]
    value_cols = [c for c in df.columns if c.lower() in LONG_VALUE_COLS]

    fmt = "unknown"
    if equip_cols and point_cols and value_cols and ts:
        fmt = "long"
    elif ts and numeric:
        fmt = "wide"

    return SourceProfile(
        source_name=source_name,
        format=fmt,
        timestamp_column=ts,
        numeric_columns=numeric,
        row_count=len(df),
        equipment_id_columns=equip_cols,
        point_name_columns=point_cols,
        value_columns=value_cols,
        issues=issues,
    )


def load_uploaded_csvs(files: list[Any]) -> list[RawSource]:
    out: list[RawSource] = []
    for f in files:
        raw = pd.read_csv(BytesIO(f.getvalue()))
        out.append(RawSource(name=f.name, df=raw, bytes_size=len(f.getvalue())))
    return out


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_") or "source"


def normalize_wide_source(
    df: pd.DataFrame,
    *,
    equipment_id: str,
    timestamp_column: str | None = None,
    site_id: str = "",
    building_id: str = "",
    source_name: str = "",
) -> dict[str, pd.DataFrame]:
    ts = timestamp_column or detect_timestamp_column(df)
    norm = normalize_timestamp(df, ts)
    issues = validate_dataframe(norm)
    if issues:
        norm.attrs["validation_issues"] = issues
    norm.attrs["equipment_id"] = equipment_id
    norm.attrs["site_id"] = site_id
    norm.attrs["building_id"] = building_id
    norm.attrs["source_name"] = source_name
    return {equipment_id: norm}


def normalize_long_source(
    df: pd.DataFrame,
    *,
    timestamp_column: str | None = None,
    equipment_col: str | None = None,
    point_col: str | None = None,
    value_col: str | None = None,
    site_id: str = "",
    building_id: str = "",
    source_name: str = "",
) -> dict[str, pd.DataFrame]:
    prof = profile_csv_source(df, source_name)
    ts = timestamp_column or prof.timestamp_column
    eq_c = equipment_col or (prof.equipment_id_columns[0] if prof.equipment_id_columns else None)
    pt_c = point_col or (prof.point_name_columns[0] if prof.point_name_columns else None)
    val_c = value_col or (prof.value_columns[0] if prof.value_columns else None)
    if not all([ts, eq_c, pt_c, val_c]):
        raise ValueError("Long format requires timestamp, equipment, point, and value columns")

    work = df.copy()
    work[ts] = pd.to_datetime(work[ts], utc=True, errors="coerce")
    work = work.dropna(subset=[ts])
    out: dict[str, pd.DataFrame] = {}
    for eq_id, grp in work.groupby(eq_c):
        eq_id = str(eq_id)
        wide = grp.pivot_table(index=ts, columns=pt_c, values=val_c, aggfunc="first")
        wide.index = pd.to_datetime(wide.index, utc=True)
        wide = wide.sort_index()
        wide.index.name = "timestamp"
        wide.attrs["equipment_id"] = eq_id
        wide.attrs["site_id"] = site_id
        wide.attrs["building_id"] = building_id
        wide.attrs["source_name"] = source_name
        out[eq_id] = wide
    return out
