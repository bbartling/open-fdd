#!/usr/bin/env python3
"""One-pass validation of refreshed HVAC CSV import vs dashboard readiness."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

from shared.data_config import DataConfig, get_config


def _rows_range(path: Path) -> dict:
    if not path.is_file():
        return {"exists": False}
    df = pd.read_csv(path, usecols=["timestamp_utc"], nrows=0)
    if "timestamp_utc" not in df.columns:
        full = pd.read_csv(path)
        if "timestamp_utc" not in full.columns:
            return {"exists": True, "rows": len(full), "error": "no timestamp_utc"}
        ts = pd.to_datetime(full["timestamp_utc"], utc=True)
    else:
        ts = pd.to_datetime(pd.read_csv(path, usecols=["timestamp_utc"])["timestamp_utc"], utc=True)
    return {
        "exists": True,
        "rows": len(ts),
        "start": str(ts.min()),
        "end": str(ts.max()),
    }


def validate(cfg: DataConfig | None = None) -> dict:
    cfg = cfg or get_config()
    report: dict = {"data_root": str(cfg.data_root), "building": cfg.building, "checks": []}

    if not cfg.data_root.is_dir():
        report["verdict"] = "NO-GO"
        report["checks"].append({"name": "data_root", "ok": False, "detail": "missing"})
        return report

    poll = cfg.poll_seconds()
    report["poll_seconds"] = poll

    wx = cfg.weather_dir / "history_wide.csv"
    wx_info = _rows_range(wx)
    report["weather"] = wx_info

    ahu1 = cfg.building_dir / "AHU_1" / "history_wide.csv"
    ahu_info = _rows_range(ahu1)
    report["ahu_1"] = ahu_info

    vav_boxes = cfg.list_vav_boxes()
    report["vav_box_count"] = len(vav_boxes)
    if vav_boxes:
        sample = cfg.vav_dir() / vav_boxes[0] / "columns.csv"
        if sample.is_file():
            cols = pd.read_csv(sample)
            roles = cols["point_role"].value_counts().to_dict() if "point_role" in cols.columns else {}
            report["vav_sample"] = {"box": vav_boxes[0], "columns": len(cols), "roles": roles}

    # Poll interval sanity
    if ahu_info.get("rows") and wx_info.get("rows"):
        ratio = ahu_info["rows"] / wx_info["rows"]
        report["checks"].append({
            "name": "ahu_weather_row_parity",
            "ok": abs(ratio - 1.0) < 0.01,
            "detail": f"ratio={ratio:.3f}",
        })

    report["checks"].append({
        "name": "vav_per_box_folders",
        "ok": len(vav_boxes) > 0,
        "detail": f"{len(vav_boxes)} boxes under {cfg.vav_dir()}",
    })

    report["checks"].append({
        "name": "poll_interval",
        "ok": poll in (300, 900),
        "detail": f"{poll}s — dashboard CONFIRM_ROWS must use this (not hardcoded 900)",
    })

    legacy_poll = 900
    if poll != legacy_poll:
        report["warnings"] = [
            f"Import uses {poll}s grid; legacy dashboard assumed {legacy_poll}s. "
            "Update POLL_SECONDS / economizer poll_seconds before switching.",
        ]

    size_mb = sum(f.stat().st_size for f in cfg.data_root.rglob("*") if f.is_file()) / 1e6
    report["data_root_size_mb"] = round(size_mb, 1)
    if size_mb > 100:
        report["git_note"] = "Do not commit full data tree to git — use data_paths.yaml + .gitignore"

    failed = [c for c in report["checks"] if not c["ok"]]
    report["verdict"] = "NO-GO" if failed else "GO (after poll_seconds wired)"

    return report


def main() -> None:
    cfg = get_config()
    report = validate(cfg)
    print(json.dumps(report, indent=2))
    sys.exit(0 if report["verdict"].startswith("GO") else 1)


if __name__ == "__main__":
    main()
