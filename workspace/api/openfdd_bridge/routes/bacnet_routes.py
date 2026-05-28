from __future__ import annotations

from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException

from ..deps import require_user
from ..paths import bacnet_poll_csv, data_dir, workspace_dir

router = APIRouter(tags=["bacnet"], dependencies=[Depends(require_user)])


@router.get("/config/bacnet")
def bacnet_config() -> dict:
    points = workspace_dir() / "bacnet" / "commissioning" / "points.csv"
    discovered = workspace_dir() / "bacnet" / "commissioning" / "points_discovered.csv"
    return {
        "points_csv": str(points),
        "points_exists": points.is_file(),
        "discovered_csv": str(discovered),
        "poll_csv": str(bacnet_poll_csv()),
        "poll_exists": bacnet_poll_csv().is_file(),
        "toolshed_readme": "bacnet_toolshed/README.md",
    }


@router.post("/ingest/bacnet")
def ingest_bacnet(site_id: str = "default") -> dict:
    poll = bacnet_poll_csv()
    if not poll.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"poll CSV not found: {poll} — run bacnet_toolshed poll_driver first",
        )
    df = pd.read_csv(poll)
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    out_dir = data_dir() / "feather_store" / "bacnet" / site_id
    out_dir.mkdir(parents=True, exist_ok=True)
    feather_path = out_dir / "latest.feather"
    df.to_feather(feather_path)
    return {
        "ok": True,
        "site_id": site_id,
        "rows": len(df),
        "feather_path": str(feather_path),
    }
