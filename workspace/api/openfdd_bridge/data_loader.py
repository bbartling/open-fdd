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


def load_site_frame(
    site_id: str,
    source: str = "bacnet",
    *,
    columns: list[str] | str | None = None,
) -> pd.DataFrame | None:
    from .feather_store import FeatherStore

    return FeatherStore().read_site(site_id, source=source, columns=columns)


def load_arrow_table_for_run(
    site_id: str | None = None,
    *,
    source: str = "bacnet",
    columns: list[str] | str | None = None,
) -> tuple[Any, str]:
    """Arrow-native frame load for FDD execution (preferred path)."""
    import pyarrow as pa

    from .feather_store import FeatherStore, _dedupe_sort

    if site_id:
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


def column_map_for_rule(model: dict, site_id: str, rule: dict) -> dict[str, str]:
    from open_fdd.engine.column_map_from_model import build_column_map_from_model_points

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
        if str(pt.get("site_id") or "") != str(site_id):
            continue
        ext = str(pt.get("external_id") or "").strip()
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
