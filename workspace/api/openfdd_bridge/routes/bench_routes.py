"""Bench validation API — cross-source BACnet vs Niagara (read-only, local lab)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..bench_validator import (
    load_bench_mapping,
    poll_cadence_report,
    validate_bacnet_vs_niagara,
    write_checkpoint_report,
)
from ..deps import require_roles
from ..niagara_store import get_station, list_stations, poll_status as niagara_poll_status
from ..bacnet_driver_store import driver_tree as bacnet_driver_tree

router = APIRouter(tags=["bench"])

_READ = Depends(require_roles("operator", "integrator", "agent"))
_POLL = Depends(require_roles("integrator", "agent"))


class BenchValidateBody(BaseModel):
    config_path: Optional[str] = None
    stale_after_polls: int = Field(default=3, ge=1, le=20)
    poll_interval_s: int = Field(default=60, ge=15, le=3600)
    write_report: bool = False
    report_label: str = "checkpoint"


@router.get("/api/bench/health", dependencies=[_READ])
def bench_health() -> dict[str, Any]:
    from ..niagara_store import health_summary as niagara_health

    stations = list_stations()
    bacnet = bacnet_driver_tree()
    return {
        "ok": True,
        "read_only": True,
        "local_bench_only": True,
        "niagara": niagara_health(),
        "niagara_stations": len(stations),
        "bacnet_devices": len(bacnet.get("devices") or []),
        "bacnet_points": sum(len(d.get("points") or []) for d in bacnet.get("devices") or []),
    }


@router.get("/api/bench/mapping", dependencies=[_READ])
def bench_mapping() -> dict[str, Any]:
    try:
        return load_bench_mapping()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/bench/validate/bacnet-vs-niagara", dependencies=[_READ])
def bench_validate_bacnet_vs_niagara(body: BenchValidateBody | None = None) -> dict[str, Any]:
    body = body or BenchValidateBody()
    cfg_path = Path(body.config_path) if body.config_path else None
    try:
        report = validate_bacnet_vs_niagara(
            config_path=cfg_path,
            stale_after_polls=body.stale_after_polls,
            poll_interval_s=body.poll_interval_s,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if body.write_report:
        paths = write_checkpoint_report(report, label=body.report_label)
        report["report_paths"] = paths
    return report


@router.get("/api/bench/poll-status", dependencies=[_READ])
def bench_poll_status(station_id: str | None = None) -> dict[str, Any]:
    from ..modbus_store import poll_status as modbus_poll_status
    from ..json_api_store import poll_status as json_poll_status

    cfg = load_bench_mapping()
    device = cfg.get("bench_device") or {}
    sid = station_id or str(device.get("niagara_station_id") or "")
    niagara = niagara_poll_status(sid) if sid and get_station(sid) else {}
    niagara_interval = 60
    if sid:
        st = get_station(sid)
        if st:
            niagara_interval = int(st.get("poll_interval_seconds") or 60)

    return {
        "bacnet_direct": {
            "source": "bacnet_direct",
            "driver_tree_devices": len(bacnet_driver_tree().get("devices") or []),
            "cadence": poll_cadence_report(source="bacnet_direct", expected_interval_s=60),
        },
        "niagara_baskstream": {
            **niagara,
            "configured_interval_s": niagara_interval,
            "cadence": poll_cadence_report(
                source="niagara_baskstream",
                station_id=sid,
                expected_interval_s=niagara_interval,
            )
            if sid
            else {},
        },
        "modbus": modbus_poll_status(),
        "json_api": json_poll_status(),
    }


@router.get("/api/bench/poll-cadence", dependencies=[_READ])
def bench_poll_cadence(
    source: str = "bacnet_direct",
    station_id: str | None = None,
    expected_interval_s: int = 60,
) -> dict[str, Any]:
    return poll_cadence_report(
        source=source,
        station_id=station_id,
        expected_interval_s=expected_interval_s,
    )
