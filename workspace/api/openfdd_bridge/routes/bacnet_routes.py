from __future__ import annotations

import csv
import re

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..commission_client import (
    bacnet_write as commission_write,
    commission_health,
    commission_status,
    get_job,
    start_discover,
    start_point_discovery,
    start_supervisory_check,
    whois as commission_whois,
)
from ..deps import require_roles, require_user
from ..paths import bacnet_poll_csv, data_dir, workspace_dir

router = APIRouter(tags=["bacnet"])

_READ = Depends(require_roles("operator", "integrator", "agent"))
_COMMISSION = Depends(require_roles("operator", "integrator", "agent"))
_WRITE = Depends(require_roles("integrator"))

_SAFE_SITE_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


class DiscoverRequest(BaseModel):
    range_low: int = Field(default=1, ge=0, le=4194303)
    range_high: int = Field(default=4194303, ge=0, le=4194303)


class DeviceInstanceRequest(BaseModel):
    device_instance: int = Field(ge=0, le=4194303)


class BacnetWriteRequest(BaseModel):
    device_instance: int = Field(ge=0, le=4194303)
    object_identifier: str
    property_identifier: str = "present-value"
    value: float | int | str | None = None
    priority: int | None = Field(default=None, ge=1, le=16)


def _validate_site_id(site_id: str) -> str:
    sid = site_id.strip()
    if not _SAFE_SITE_ID.match(sid):
        raise HTTPException(status_code=400, detail="invalid site_id")
    return sid


def _proxy_error(status: int, payload: object) -> HTTPException:
    detail = payload if isinstance(payload, dict) else {"error": str(payload)}
    return HTTPException(status_code=status, detail=detail)


@router.get("/config/bacnet", dependencies=[_READ])
def bacnet_config() -> dict:
    points = workspace_dir() / "bacnet" / "commissioning" / "points.csv"
    discovered = workspace_dir() / "bacnet" / "commissioning" / "points_discovered.csv"
    commission_ok = False
    commission_detail: dict | None = None
    status_code, payload = commission_health()
    if status_code == 200 and isinstance(payload, dict):
        commission_ok = bool(payload.get("ok"))
        commission_detail = payload
    return {
        "points_csv": str(points),
        "points_exists": points.is_file(),
        "discovered_csv": str(discovered),
        "discovered_exists": discovered.is_file(),
        "poll_csv": str(bacnet_poll_csv()),
        "poll_exists": bacnet_poll_csv().is_file(),
        "toolshed_readme": "bacnet_toolshed/README.md",
        "commission_agent_ok": commission_ok,
        "commission_agent": commission_detail,
    }


@router.get("/api/bacnet/commission/status", dependencies=[_READ])
def bacnet_commission_status() -> dict:
    status_code, payload = commission_status()
    if status_code != 200:
        raise _proxy_error(status_code, payload)
    return payload  # type: ignore[return-value]


@router.get("/api/bacnet/inventory", dependencies=[_READ])
def bacnet_inventory() -> dict:
    """Grouped device → points from points_discovered.csv (after CSV discover job)."""
    discovered = workspace_dir() / "bacnet" / "commissioning" / "points_discovered.csv"
    if not discovered.is_file():
        return {"ok": True, "devices": [], "point_count": 0, "path": str(discovered)}
    devices: dict[str, dict] = {}
    point_count = 0
    with discovered.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            inst = str(row.get("device_instance") or "").strip()
            if not inst:
                continue
            dev = devices.setdefault(
                inst,
                {
                    "device_instance": inst,
                    "device_address": str(row.get("device_address") or ""),
                    "points": [],
                },
            )
            if not dev["device_address"] and row.get("device_address"):
                dev["device_address"] = str(row["device_address"])
            obj_type = str(row.get("object_type") or "")
            obj_inst = str(row.get("object_instance") or "")
            point = {
                "object_identifier": f"{obj_type},{obj_inst}" if obj_type else "",
                "object_name": str(row.get("object_name") or ""),
                "description": str(row.get("description") or ""),
                "present_value": str(row.get("present_value") or ""),
                "units": str(row.get("units") or ""),
                "point_id": str(row.get("point_id") or ""),
            }
            dev["points"].append(point)
            point_count += 1
    device_list = sorted(devices.values(), key=lambda d: int(d["device_instance"]))
    for dev in device_list:
        dev["point_count"] = len(dev["points"])
    return {
        "ok": True,
        "devices": device_list,
        "point_count": point_count,
        "path": str(discovered),
    }


@router.post("/api/bacnet/discover", dependencies=[_COMMISSION])
def bacnet_discover_devices(body: DiscoverRequest) -> dict:
    if body.range_low > body.range_high:
        raise HTTPException(status_code=400, detail="range_low must be <= range_high")
    status_code, payload = start_discover(body.range_low, body.range_high)
    if status_code not in (200, 202):
        raise _proxy_error(status_code, payload)
    return payload  # type: ignore[return-value]


@router.post("/api/bacnet/whois", dependencies=[_COMMISSION])
def bacnet_whois(body: DiscoverRequest) -> dict:
    status_code, payload = commission_whois(body.range_low, body.range_high)
    if status_code != 200:
        raise _proxy_error(status_code, payload)
    return payload  # type: ignore[return-value]


@router.post("/api/bacnet/point-discovery", dependencies=[_COMMISSION])
def bacnet_point_discovery(body: DeviceInstanceRequest) -> dict:
    status_code, payload = start_point_discovery(body.device_instance)
    if status_code not in (200, 202):
        raise _proxy_error(status_code, payload)
    return payload  # type: ignore[return-value]


@router.post("/api/bacnet/supervisory-check", dependencies=[_COMMISSION])
def bacnet_supervisory_check(body: DeviceInstanceRequest) -> dict:
    status_code, payload = start_supervisory_check(body.device_instance)
    if status_code not in (200, 202):
        raise _proxy_error(status_code, payload)
    return payload  # type: ignore[return-value]


@router.post("/api/bacnet/write", dependencies=[_WRITE])
def bacnet_write_property(body: BacnetWriteRequest) -> dict:
    status_code, payload = commission_write(
        body.device_instance,
        body.object_identifier,
        body.property_identifier,
        body.value,
        body.priority,
    )
    if status_code != 200:
        raise _proxy_error(status_code, payload)
    return payload  # type: ignore[return-value]


@router.get("/api/bacnet/jobs/{job_id}", dependencies=[_COMMISSION])
def bacnet_job_status(job_id: str) -> dict:
    if not re.match(r"^[a-f0-9]{8,32}$", job_id):
        raise HTTPException(status_code=400, detail="invalid job_id")
    status_code, payload = get_job(job_id)
    if status_code != 200:
        raise _proxy_error(status_code, payload)
    return payload  # type: ignore[return-value]


@router.post("/ingest/bacnet", dependencies=[_READ])
def ingest_bacnet(site_id: str = "default") -> dict:
    site_id = _validate_site_id(site_id)
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
