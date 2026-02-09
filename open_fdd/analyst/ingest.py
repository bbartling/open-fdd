#!/usr/bin/env python3
"""
Ingest SP_Data.zip — zip-of-zips, one CSV per point.
Extracts equipment catalog and column mapping from path headers.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd

from open_fdd.analyst.config import AnalystConfig, default_analyst_config


def _parse_path(path_str: str) -> dict[str, str]:
    """Parse 'Site / Building / Floor / Area / Equipment_Name / Point' -> dict."""
    path_str = path_str.strip('"').strip()
    parts = [p.strip() for p in path_str.split("/")]
    return {
        "site": parts[0] if len(parts) > 0 else "",
        "building": parts[1] if len(parts) > 1 else "",
        "floor": parts[2] if len(parts) > 2 else "",
        "area": parts[3] if len(parts) > 3 else "",
        "equipment": parts[4] if len(parts) > 4 else "",
        "point": parts[5] if len(parts) > 5 else "",
    }


def _csv_path_from_zip(z: zipfile.ZipFile, filename: str) -> str | None:
    """Read first row (path) from a CSV inside zip."""
    try:
        with z.open(filename) as f:
            first = f.readline().decode("utf-8", errors="replace").strip().strip('"')
            return first
    except Exception:
        return None


def _normalize_equipment_id(equipment: str) -> str:
    """B203_Heat Pump 33 -> hp_B203_33."""
    m = re.search(r"Heat Pump\s*(\d+)", equipment, re.I)
    num = m.group(1) if m else "0"
    prefix = re.sub(r"_?Heat Pump.*", "", equipment, flags=re.I).strip()
    prefix = re.sub(r"[^a-zA-Z0-9_]", "_", prefix).strip("_") or "hp"
    return f"hp_{prefix}_{num}"


def process_inner_zip(
    inner_path: Path, zip_parent: Path
) -> list[dict[str, Any]]:
    """
    Process one inner zip. Returns list of {equipment_id, point_type, combined_col, path}.
    """
    rows = []
    with zipfile.ZipFile(inner_path, "r") as z:
        namelist = z.namelist()
        point_files = [
            n
            for n in namelist
            if n.endswith(".csv")
            and "combined" not in n.lower()
            and not n.startswith(".")
        ]
        for pf in point_files:
            path_str = _csv_path_from_zip(z, pf)
            if not path_str:
                continue
            parsed = _parse_path(path_str)
            equipment = parsed.get("equipment", "")
            point = parsed.get("point", "")
            if not equipment or not point:
                continue
            point_type = "dat" if "DAT" in point or "dat" in point.lower() else None
            if not point_type:
                if "Zone" in point or "zone" in point.lower():
                    point_type = "zone_temp"
                elif "Fan" in point or "fan" in point.lower():
                    point_type = "fan_status"
            if not point_type:
                continue
            eq_id = _normalize_equipment_id(equipment)
            base = Path(pf).stem
            rows.append({
                "equipment_id": eq_id,
                "equipment_label": equipment,
                "point_type": point_type,
                "csv_file": pf,
                "combined_col": base,
                "path": path_str,
                "inner_zip": inner_path.name,
            })
    return rows


def extract_outer_zip(sp_data_zip: Path, sp_extract_dir: Path) -> Path:
    """Extract SP_Data.zip to sp_extract_dir."""
    sp_extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(sp_data_zip, "r") as z:
        z.extractall(sp_extract_dir)
    inner_dir = sp_extract_dir / "SP_Data"
    return inner_dir if inner_dir.exists() else sp_extract_dir


def run_ingest(
    config: AnalystConfig | None = None,
) -> pd.DataFrame:
    """Run full ingest. Returns equipment catalog DataFrame."""
    cfg = config or default_analyst_config()
    data_root = cfg.data_root
    equipment_catalog = cfg.equipment_catalog

    print("Extracting outer zip...")
    inner_dir = extract_outer_zip(cfg.sp_data_zip, cfg.sp_extract_dir)
    inner_zips = sorted(inner_dir.glob("*.zip"))
    print(f"Found {len(inner_zips)} inner zips")

    all_rows = []
    for zp in inner_zips:
        rows = process_inner_zip(zp, inner_dir)
        all_rows.extend(rows)

    df = pd.DataFrame(all_rows)
    if df.empty:
        print("No equipment found.")
        return df

    data_root.mkdir(parents=True, exist_ok=True)
    df.to_csv(equipment_catalog, index=False)
    print(f"Equipment catalog saved: {equipment_catalog}")
    print(f"  {len(df)} point mappings")
    print(f"  {df['equipment_id'].nunique()} unique equipment")
    return df


if __name__ == "__main__":
    run_ingest()
