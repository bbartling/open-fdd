#!/usr/bin/env python3
"""
Build one heat_pumps.csv from combined CSVs + equipment catalog.
Columns: equipment_id, timestamp, sat (discharge), zt (zone temp), fan_status.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pandas as pd

from open_fdd.analyst.config import AnalystConfig, default_analyst_config


def load_combined_csv_from_zip(zip_path: Path) -> pd.DataFrame | None:
    """Extract and load combined CSV from inner zip."""
    with zipfile.ZipFile(zip_path, "r") as z:
        combined = [
            n
            for n in z.namelist()
            if "combined" in n.lower() and n.endswith(".csv")
        ]
        if not combined:
            return None
        with z.open(combined[0]) as f:
            df = pd.read_csv(f)
    df.columns = df.columns.str.strip().str.strip('"').str.replace("\ufeff", "")
    date_col = next((c for c in df.columns if "date" in c.lower()), df.columns[0])
    date_ser = df[date_col].astype(str).str.replace(r"\s+[A-Z]{3}$", "", regex=True)
    df["Date"] = pd.to_datetime(date_ser, format="%m/%d/%Y %I:%M:%S %p", errors="coerce")
    df = df.dropna(subset=["Date"])
    df = df.sort_values("Date").reset_index(drop=True)
    return df


def build_equipment_df(
    combined: pd.DataFrame,
    catalog: pd.DataFrame,
    inner_zip_name: str,
    resample_freq: str = "5min",
) -> list[pd.DataFrame]:
    """For one combined CSV, build one DataFrame per equipment."""
    cat = catalog[catalog["inner_zip"] == inner_zip_name]
    out = []
    for eq_id in cat["equipment_id"].unique():
        eq_cat = cat[cat["equipment_id"] == eq_id]
        cols = {}
        for _, row in eq_cat.iterrows():
            col = row["combined_col"]
            pt = row["point_type"]
            if col in combined.columns:
                s = pd.to_numeric(combined[col], errors="coerce")
                cols[pt] = s
        if not cols:
            continue
        df = pd.DataFrame({"timestamp": combined["Date"]})
        df["sat"] = cols.get("dat", pd.Series(dtype=float))
        df["zt"] = cols.get("zone_temp", pd.Series(dtype=float))
        df["fan_status"] = cols.get("fan_status", pd.Series(dtype=float))
        df = df.set_index("timestamp")
        df = df.resample(resample_freq).mean()
        if "fan_status" in df.columns:
            df["fan_status"] = df["fan_status"].ffill().fillna(0)
        df = df.dropna(how="all")
        df = df.reset_index()
        df["equipment_id"] = eq_id
        out.append(df)
    return out


def run_to_dataframe(config: AnalystConfig | None = None) -> None:
    """Build one heat_pumps.csv with all equipment."""
    cfg = config or default_analyst_config()
    equipment_catalog = cfg.equipment_catalog
    heat_pumps_csv = cfg.heat_pumps_csv
    data_root = cfg.data_root
    inner_dir = cfg.sp_extract_dir / "SP_Data"

    if not equipment_catalog.exists():
        raise FileNotFoundError(f"Run ingest.py first. Missing {equipment_catalog}")

    if not inner_dir.exists():
        raise FileNotFoundError(f"Run ingest.py first. Missing {inner_dir}")

    catalog = pd.read_csv(equipment_catalog)
    data_root.mkdir(parents=True, exist_ok=True)
    all_dfs = []

    for zip_path in sorted(inner_dir.glob("*.zip")):
        combined = load_combined_csv_from_zip(zip_path)
        if combined is None:
            continue
        for df in build_equipment_df(
            combined, catalog, zip_path.name, resample_freq=cfg.resample_freq
        ):
            all_dfs.append(df)

    if not all_dfs:
        print("No data built.")
        return

    big = pd.concat(all_dfs, ignore_index=True)
    big = big[["equipment_id", "timestamp", "sat", "zt", "fan_status"]]
    big.to_csv(heat_pumps_csv, index=False)
    print(f"Saved {heat_pumps_csv}: {len(big)} rows, {big['equipment_id'].nunique()} equipment")


if __name__ == "__main__":
    run_to_dataframe()
