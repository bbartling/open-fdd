from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .paths import data_dir


def sample_csv_path() -> Path:
    return data_dir() / "samples" / "demo_site.csv"


def load_demo_dataframe(site_id: str | None = None) -> pd.DataFrame:
    path = sample_csv_path()
    if path.is_file():
        df = pd.read_csv(path, parse_dates=["timestamp"])
        if site_id and "site_id" in df.columns:
            df = df[df["site_id"] == site_id]
        return df
    # Synthetic fallback
    import numpy as np

    n = 120
    ts = pd.date_range("2025-01-01", periods=n, freq="5min", tz="UTC")
    rng = np.random.default_rng(42)
    return pd.DataFrame(
        {
            "timestamp": ts,
            "site_id": site_id or "demo",
            "SAT": 55.0 + rng.normal(0, 2, n),
            "RAT": 72.0 + rng.normal(0, 1.5, n),
            "OAT": 35.0 + rng.normal(0, 3, n),
        }
    )


DRIVER_SOURCES = ("bacnet", "modbus", "json_api")


def load_site_frame(
    site_id: str,
    source: str = "bacnet",
    *,
    columns: list[str] | str | None = None,
) -> pd.DataFrame | None:
    from .feather_store import FeatherStore

    return FeatherStore().read_site(site_id, source=source, columns=columns)


def _merge_timeseries_frames(left: pd.DataFrame, right: pd.DataFrame) -> pd.DataFrame:
    """Align irregular driver polls by nearest timestamp (30 min tolerance)."""
    key_cols = {"timestamp", "site_id"}
    extra = [c for c in right.columns if c not in left.columns and c not in key_cols]
    if not extra:
        return left
    l = left.sort_values("timestamp").copy()
    r = right.sort_values("timestamp")[["timestamp", *extra]].copy()
    l["timestamp"] = pd.to_datetime(l["timestamp"], utc=True, errors="coerce")
    r["timestamp"] = pd.to_datetime(r["timestamp"], utc=True, errors="coerce")
    merged = pd.merge_asof(
        l,
        r,
        on="timestamp",
        direction="nearest",
        tolerance=pd.Timedelta("30min"),
    )
    return merged.sort_values("timestamp").reset_index(drop=True)


def load_merged_site_frame(
    site_id: str,
    *,
    columns: list[str] | str | None = None,
    sources: tuple[str, ...] = DRIVER_SOURCES,
) -> pd.DataFrame | None:
    """Merge historian columns from BACnet, Modbus, and JSON API for cross-source FDD."""
    frames: list[pd.DataFrame] = []
    for src in sources:
        frame = load_site_frame(site_id, source=src, columns=columns)
        if frame is not None and not frame.empty:
            frames.append(frame)
    if not frames:
        return None
    merged = frames[0]
    for frame in frames[1:]:
        merged = _merge_timeseries_frames(merged, frame)
    return merged


def load_arrow_table_for_run(
    site_id: str | None = None,
    *,
    source: str = "bacnet",
    columns: list[str] | str | None = None,
) -> tuple[Any, str]:
    """Arrow-native frame load for FDD execution (preferred path)."""
    import pyarrow as pa

    from .feather_store import _dedupe_sort

    if site_id:
        if source == "bacnet":
            frame = load_merged_site_frame(site_id, columns=columns)
            if frame is not None and not frame.empty:
                return pa.Table.from_pandas(_dedupe_sort(frame)), "feather"
        else:
            from .feather_store import FeatherStore

            table = FeatherStore().read_site_table(site_id, source=source, columns=columns)
            if table is not None:
                if hasattr(table, "num_rows") and table.num_rows > 0:
                    return table, "feather"
                if hasattr(table, "empty") and not table.empty:
                    return pa.Table.from_pandas(_dedupe_sort(table)), "feather"
    demo = load_demo_dataframe(site_id)
    if demo.empty and site_id:
        demo = load_demo_dataframe(None)
    return pa.Table.from_pandas(demo), "demo"


def load_frame_for_run(
    site_id: str | None = None,
    *,
    source: str = "bacnet",
    columns: list[str] | str | None = None,
) -> tuple[pd.DataFrame, str]:
    """Return the best available frame for a site plus its origin.

    Prefers real feather-stored timeseries; falls back to the demo CSV so the
    batch runner and Rule Lab still work on a fresh edge box.
    """
    if site_id:
        if source == "bacnet":
            frame = load_merged_site_frame(site_id, columns=columns)
        else:
            frame = load_site_frame(site_id, source=source, columns=columns)
        if frame is not None and not frame.empty:
            return frame, "feather"
    demo = load_demo_dataframe(site_id)
    if demo.empty and site_id:
        # BRICK site id may not match the sample data's site_id column; still
        # give the rule something to run against on a fresh box.
        demo = load_demo_dataframe(None)
    return demo, "demo"


def records_from_dataframe(df: pd.DataFrame, limit: int = 500) -> list[dict[str, Any]]:
    sample = df.head(limit).copy()
    if "timestamp" in sample.columns:
        sample["timestamp"] = sample["timestamp"].astype(str)
    return sample.to_dict(orient="records")


def rows_for_evaluate(df: pd.DataFrame, limit: int = 500) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for _, row in df.head(limit).iterrows():
        item = row.to_dict()
        if "timestamp" in item and hasattr(item["timestamp"], "isoformat"):
            item["timestamp"] = item["timestamp"].isoformat()
        temp = None
        for key in ("SAT", "supply_air_temp", "degF"):
            if key in item and item[key] is not None:
                temp = item[key]
                break
        item["temp"] = temp
        rows.append(item)
    return rows


def enrich_rows_with_column_map(rows: list[dict[str, Any]], column_map: dict[str, str]) -> list[dict[str, Any]]:
    """Add BRICK/fdd_input keys onto each row using external_id column values."""
    if not column_map:
        return rows
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        for rule_key, col_name in column_map.items():
            if not rule_key or not col_name:
                continue
            if col_name in item and rule_key not in item:
                item[rule_key] = item[col_name]
        out.append(item)
    return out


def historian_columns_for_rule(
    model: dict,
    site_id: str,
    rule: dict,
    *,
    available_columns: set[str] | list[str] | None = None,
) -> list[str]:
    """Historian column names for all points matched by rule bindings (brick / equipment / point)."""
    from .model_point_utils import point_site_id
    from .timeseries_api import plot_column_name

    bindings = rule.get("bindings") if isinstance(rule.get("bindings"), dict) else {}
    point_ids = {str(x) for x in bindings.get("point_ids") or [] if str(x).strip()}
    equipment_ids = {str(x) for x in bindings.get("equipment_ids") or [] if str(x).strip()}
    brick_types = {str(x) for x in bindings.get("brick_types") or [] if str(x).strip()}
    if not point_ids and not equipment_ids and not brick_types:
        return []

    cols: list[str] = []
    sid = str(site_id or "").strip()
    available = set(available_columns) if available_columns is not None else None
    for pt in model.get("points") or []:
        if not isinstance(pt, dict):
            continue
        if point_site_id(pt, model) != sid:
            continue
        pid = str(pt.get("id") or "").strip()
        eq_id = str(pt.get("equipment_id") or "").strip()
        brick = str(pt.get("brick_type") or "").strip()
        matched = False
        if point_ids and pid in point_ids:
            matched = True
        elif equipment_ids and eq_id in equipment_ids:
            matched = True
        elif brick_types and brick in brick_types:
            matched = True
        if not matched:
            continue
        from .timeseries_api import historian_column_candidates, resolve_historian_column

        if available is not None:
            col = resolve_historian_column(pt, available)
            if col not in available:
                continue
        else:
            col = plot_column_name(pt)
        if col:
            cols.append(col)
    return sorted(set(cols))


def historian_columns_for_rule_resolved(
    model: dict,
    site_id: str,
    rule: dict,
    available_columns: set[str] | list[str],
) -> list[str]:
    """Binding-matched historian columns that exist in a loaded frame."""
    return historian_columns_for_rule(
        model,
        site_id,
        rule,
        available_columns=available_columns,
    )


def column_map_for_rule(model: dict, site_id: str, rule: dict) -> dict[str, str]:
    from open_fdd.arrow_runtime.column_map_from_model import build_column_map_from_model_points

    base = build_column_map_from_model_points(model, site_id)
    extra = rule.get("column_map") if isinstance(rule.get("column_map"), dict) else {}
    base.update({str(k): str(v) for k, v in extra.items() if k and v})
    bindings = rule.get("bindings") if isinstance(rule.get("bindings"), dict) else {}
    point_ids = {str(x) for x in bindings.get("point_ids") or [] if str(x).strip()}
    if not point_ids:
        return base
    scoped: dict[str, str] = {}
    for pt in model.get("points") or []:
        if not isinstance(pt, dict) or str(pt.get("id") or "") not in point_ids:
            continue
        from .model_point_utils import point_historian_column, point_site_id

        if point_site_id(pt, model) != str(site_id):
            continue
        ext = str(pt.get("external_id") or "").strip() or point_historian_column(pt)
        if not ext:
            continue
        for key in (str(pt.get("fdd_input") or "").strip(), str(pt.get("brick_type") or "").strip()):
            if key:
                scoped[key] = ext
    if not scoped:
        return base
    merged = base.copy()
    merged.update(scoped)
    return merged
