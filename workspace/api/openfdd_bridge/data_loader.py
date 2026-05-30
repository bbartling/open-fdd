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


def load_site_frame(site_id: str, source: str = "bacnet") -> pd.DataFrame | None:
    from .feather_store import FeatherStore

    return FeatherStore().read_site(site_id, source=source)


def load_frame_for_run(site_id: str | None = None, *, source: str = "bacnet") -> tuple[pd.DataFrame, str]:
    """Return the best available frame for a site plus its origin.

    Prefers real feather-stored timeseries; falls back to the demo CSV so the
    batch runner and Rule Lab still work on a fresh edge box.
    """
    if site_id:
        frame = load_site_frame(site_id, source=source)
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
