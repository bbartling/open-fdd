#!/usr/bin/env python3
"""Convert temperature columns in a building tree from °F to °C for metric twin CI."""
from __future__ import annotations

import csv
import shutil
import sys
from pathlib import Path

TEMP_HINTS = (
    "temp",
    "sat",
    "mat",
    "rat",
    "oat",
    "oa_t",
    "zone_t",
    "zn_t",
    "dry_bulb",
    "web_oa",
    "chw_supply",
    "chw_return",
    "hw_supply",
    "leaving",
    "entering",
)


def is_temp_role(role: str, col: str) -> bool:
    blob = f"{role} {col}".lower()
    if "static" in blob or "pressure" in blob:
        return False
    if "flow" in blob or "cfm" in blob:
        return False
    return any(h in blob for h in TEMP_HINTS)


PRESSURE_HINTS = (
    "duct_static",
    "duct-static",
    "static_pressure",
    "static-pressure",
    "in_wc",
    "inwc",
    "in_wg",
    "inwg",
)
FLOW_HINTS = (
    "zone_flow",
    "airflow",
    "cfm",
    "vav_total_flow",
    "min_flow",
    "chw_flow",
)


def is_pressure_role(role: str, col: str) -> bool:
    blob = f"{role} {col}".lower()
    return any(h in blob for h in PRESSURE_HINTS)


def is_flow_role(role: str, col: str) -> bool:
    blob = f"{role} {col}".lower()
    if "temp" in blob:
        return False
    return any(h in blob for h in FLOW_HINTS)


def f_to_c(x: float) -> float:
    return (x - 32.0) * 5.0 / 9.0


def inwc_to_pa(x: float) -> float:
    return x * 248.84


def cfm_to_lps(x: float) -> float:
    return x * 0.471947


def convert_equipment(eq_dir: Path) -> None:
    cols_path = eq_dir / "columns.csv"
    hist_path = eq_dir / "history_wide.csv"
    if not cols_path.is_file() or not hist_path.is_file():
        return
    temp_cols: set[str] = set()
    pressure_cols: set[str] = set()
    flow_cols: set[str] = set()
    with cols_path.open() as f:
        r = csv.DictReader(f)
        for row in r:
            col = (row.get("col") or row.get("column") or "").strip()
            role = (row.get("point_role") or row.get("role") or "").strip()
            if not col:
                continue
            if is_temp_role(role, col):
                temp_cols.add(col)
            elif is_pressure_role(role, col):
                pressure_cols.add(col)
            elif is_flow_role(role, col):
                flow_cols.add(col)
    if not temp_cols and not pressure_cols and not flow_cols:
        return
    with hist_path.open() as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    converters = (
        (temp_cols, f_to_c),
        (pressure_cols, inwc_to_pa),
        (flow_cols, cfm_to_lps),
    )
    for row in rows:
        for cols, fn in converters:
            for c in cols:
                if c not in row or row[c] in (None, ""):
                    continue
                try:
                    row[c] = f"{fn(float(row[c])):.6f}"
                except ValueError:
                    pass
    with hist_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    for eq in dst.iterdir():
        if eq.is_dir():
            convert_equipment(eq)
    print(f"metric twin written to {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
