from __future__ import annotations

import csv
import re
from typing import Any, Literal

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from bacnet_toolshed.models import (
    DeviceInstanceRequest,
    DiscoverRequest,
    ReadMultiplePropertiesRequestWrapper,
    ReadPriorityArrayRequest,
    SingleReadRequest,
    WritePropertyRequest,
)

from ..bacnet_driver_store import (
    clear_registry,
    delete_device,
    delete_point,
    driver_tree,
    remap_device,
    set_device_poll,
    set_point_poll,
    sync_discovery,
)
from ..bacnet_model_sync import merge_device_into_model
from ..commission_client import (
    bacnet_priority_array as commission_priority_array,
    bacnet_read as commission_read,
    bacnet_read_multiple as commission_read_multiple,
    bacnet_write as commission_write,
    commission_health,
    commission_status,
    get_job,
    server_points as commission_server_points,
    start_discover,
    start_point_discovery,
    start_supervisory_check,
    whois as commission_whois,
)
from ..deps import require_roles
from ..bacnet_poll_ingest import ingest_poll_samples_to_feather
from ..commission_client import commission_poll_once, commission_poll_status
from ..paths import bacnet_poll_csv, data_dir, workspace_dir

router = APIRouter(tags=["bacnet"])

_READ = Depends(require_roles("operator", "integrator", "agent"))
_COMMISSION = Depends(require_roles("operator", "integrator", "agent"))
_WRITE = Depends(require_roles("integrator"))
_INTEGRATOR = Depends(require_roles("integrator"))


class ImportToModelBody(BaseModel):
    device_instance: int = Field(ge=0, le=4194303)
    device_address: str = ""
    site_id: str | None = None
    equipment_name: str | None = None
    objects: list[dict[str, Any]] | None = None


class SyncDiscoveryBody(BaseModel):
    device_instance: int = Field(ge=0, le=4194303)
    device_address: str = ""
    objects: list[dict[str, Any]] = Field(default_factory=list)
    replace: bool = False


class PointPollBody(BaseModel):
    point_id: str
    enabled: bool = True
    poll_interval_s: Literal[60, 300, 600, 900] = 60


class DevicePollBody(BaseModel):
    device_instance: int = Field(ge=0, le=4194303)
    enabled: bool = True
    poll_interval_s: Literal[60, 300, 600, 900] = 60


class RemapDeviceBody(BaseModel):
    device_instance: int = Field(ge=0, le=4194303)
    new_device_instance: int | None = Field(default=None, ge=0, le=4194303)
    new_device_address: str | None = None

_SAFE_SITE_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


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
    server_pts: list[dict] = []
    sp_status, sp_payload = commission_server_points()
    if sp_status == 200 and isinstance(sp_payload, dict):
        server_pts = sp_payload.get("points") or []
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
        "openfdd_server_points": server_pts,
    }


@router.get("/api/bacnet/commission/status", dependencies=[_READ])
def bacnet_commission_status() -> dict:
    status_code, payload = commission_status()
    if status_code != 200:
        raise _proxy_error(status_code, payload)
    return payload  # type: ignore[return-value]


@router.get("/api/bacnet/server/points", dependencies=[_READ])
def bacnet_server_points() -> dict:
    status_code, payload = commission_server_points()
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


@router.post("/api/bacnet/import-to-model", dependencies=[_INTEGRATOR])
def bacnet_import_to_model(body: ImportToModelBody) -> dict:
    """Merge BACnet discovery into model.json (integrator role)."""
    try:
        return merge_device_into_model(
            device_instance=body.device_instance,
            device_address=body.device_address,
            objects=body.objects,
            site_id=body.site_id,
            equipment_name=body.equipment_name,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/bacnet/driver/tree", dependencies=[_READ])
def bacnet_driver_tree() -> dict:
    return driver_tree()


@router.post("/api/bacnet/driver/sync-discovery", dependencies=[_COMMISSION])
def bacnet_sync_discovery(body: SyncDiscoveryBody) -> dict:
    try:
        return sync_discovery(
            device_instance=body.device_instance,
            device_address=body.device_address,
            objects=body.objects,
            replace=body.replace,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/api/bacnet/driver/point", dependencies=[_COMMISSION])
def bacnet_set_point_poll(body: PointPollBody) -> dict:
    try:
        return set_point_poll(
            point_id=body.point_id,
            enabled=body.enabled,
            poll_interval_s=body.poll_interval_s,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/api/bacnet/driver/device", dependencies=[_COMMISSION])
def bacnet_set_device_poll(body: DevicePollBody) -> dict:
    try:
        return set_device_poll(
            device_instance=body.device_instance,
            enabled=body.enabled,
            poll_interval_s=body.poll_interval_s,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/api/bacnet/driver/point/{point_id}", dependencies=[_COMMISSION])
def bacnet_delete_point(point_id: str) -> dict:
    return delete_point(point_id=point_id)


@router.delete("/api/bacnet/driver/device/{device_instance}", dependencies=[_COMMISSION])
def bacnet_delete_device(device_instance: int) -> dict:
    return delete_device(device_instance=device_instance)


@router.delete("/api/bacnet/driver/registry", dependencies=[_COMMISSION])
def bacnet_clear_registry() -> dict:
    """Clear all BACnet devices from driver CSVs, poll samples, and data model."""
    return clear_registry(sync_model=True, sync_ttl=True)


@router.patch("/api/bacnet/driver/device/remap", dependencies=[_COMMISSION])
def bacnet_remap_device(body: RemapDeviceBody) -> dict:
    if body.new_device_instance is None and not (body.new_device_address or "").strip():
        raise HTTPException(status_code=400, detail="provide new_device_instance and/or new_device_address")
    try:
        return remap_device(
            device_instance=body.device_instance,
            new_device_instance=body.new_device_instance,
            new_device_address=(body.new_device_address or "").strip() or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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


@router.post("/api/bacnet/read", dependencies=[_COMMISSION])
def bacnet_read_property(body: SingleReadRequest) -> dict:
    status_code, payload = commission_read(
        body.device_instance,
        body.object_identifier,
        body.property_identifier,
    )
    if status_code != 200:
        raise _proxy_error(status_code, payload)
    return payload  # type: ignore[return-value]


@router.post("/api/bacnet/read-multiple", dependencies=[_COMMISSION])
def bacnet_read_multiple_properties(body: ReadMultiplePropertiesRequestWrapper) -> dict:
    requests = [
        {"object_identifier": r.object_identifier, "property_identifier": r.property_identifier}
        for r in body.requests
    ]
    status_code, payload = commission_read_multiple(body.device_instance, requests)
    if status_code != 200:
        raise _proxy_error(status_code, payload)
    return payload  # type: ignore[return-value]


@router.post("/api/bacnet/priority-array", dependencies=[_COMMISSION])
def bacnet_read_priority_array(body: ReadPriorityArrayRequest) -> dict:
    status_code, payload = commission_priority_array(
        body.device_instance, body.object_identifier
    )
    if status_code != 200:
        raise _proxy_error(status_code, payload)
    return payload  # type: ignore[return-value]


@router.post("/api/bacnet/point-discovery", dependencies=[_COMMISSION])
def bacnet_point_discovery(body: DeviceInstanceRequest) -> dict:
    status_code, payload = start_point_discovery(body.device_instance, body.device_address)
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
def bacnet_write_property(body: WritePropertyRequest) -> dict:
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


@router.get("/api/bacnet/poll/status", dependencies=[_READ])
def bacnet_poll_status() -> dict:
    code, payload = commission_poll_status()
    if code != 200:
        raise _proxy_error(code, payload)
    return payload  # type: ignore[return-value]


@router.post("/api/bacnet/poll/once", dependencies=[_COMMISSION])
def bacnet_trigger_poll() -> dict:
    code, payload = commission_poll_once()
    if code != 200:
        raise _proxy_error(code, payload)
    ingest = ingest_poll_samples_to_feather()
    return {"poll": payload, "ingest": ingest}


@router.post("/internal/bacnet/ingest-samples")
def internal_ingest_poll_samples(request: Request) -> dict:
    host = request.client.host if request.client else ""
    if host not in {"127.0.0.1", "::1"}:
        raise HTTPException(status_code=403, detail="localhost only")
    return ingest_poll_samples_to_feather()


@router.post("/ingest/bacnet", dependencies=[_READ])
def ingest_bacnet(site_id: str | None = None) -> dict:
    if site_id:
        _validate_site_id(site_id)
    result = ingest_poll_samples_to_feather()
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("reason", "ingest failed"))
    return result
